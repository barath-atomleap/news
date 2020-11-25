import base64
import requests
from unidecode import unidecode
from bson import ObjectId
import datetime
from delphai_utils.formatting import clean_url
from utils.utils import check_language, save_blob, is_text_in_english, translate_to_english
from delphai_utils.logging import logging
from delphai_utils.db import db_sync
from .news_processing import create_company_to_description_dict, enrich_company_to_description_dict
from .news_processing import match_nes_to_db_companies, news_boilerplater, get_company_nes_from_article

db = db_sync
news = db.news
news.create_index('url')
news.create_index([('company_id', 1), ('url', 1)], unique=True)


def articles_data(company_id, start_row, fetch_count):
  try:
    logging.info(f'Retrieving articles for {company_id} page {start_row}')
    skip = (start_row - 1) * fetch_count

    news_articles = news.aggregate([{
        "$match": {
            "company_id": ObjectId(company_id)
        }
    }, {
        "$project": {
            "_id": 0,
            "description": 1,
            "mentions": 1,
            "is_translated": 1,
            "date": {
                '$dateToString': {
                    'format': '%Y-%m-%d',
                    'date': {
                        '$toDate': '$date'
                    }
                }
            },
            "title": 1,
            "url": 1
        }
    }, {
        "$sort": {
            "date": -1
        }
    }, {
        "$facet": {
            "total": [{
                "$count": "count"
            }],
            "articles": [{
                "$skip": skip
            }, {
                "$limit": int(fetch_count)
            }]
        }
    }])

    results = list(news_articles)[0]
    results['total'] = results['total'][0].get('count', 0) if len(results['total']) > 0 else 0

    return results
  except Exception as e:
    logging.error(f'Error: {e}')
    return {}


def save_article(companies: list,
                 page_url: str,
                 html: str,
                 test_mode: bool,
                 source: str,
                 date: str = '',
                 get_named_entities: bool = False,
                 no_products: bool = False,
                 topic: str = '',
                 title: str = '',
                 content: str = '',
                 translate: bool = True):
  """
  Receives a page from a news source, its html content and adds this news article to our DB.
  If a company from our DB is mentioned in this article, then the article is assigned to the company and it will
  appear in its news tab. Old implementation: If there is at least one mentioned company, then we also detect
  sentences in the text that discuss products and return the most relevant sentence.
  Args:
      companies: list of dictionaries with (_id or url, name) for each company
      page_url: url of the article
      html: html content of the article
      test_mode: return results instead of saving
      source: source of the article
      date: string with article date (optional)
      get_named_entities: tries to recognize entities automatically
      no_products: skip products detection
      topic: topic of the article
      title: title of the article
      content: content of the article
      translate: translate the article
  Returns: article ids in DB
  """
  try:
    message = ''
    content_lang = ''
    logging.info(f'Saving article from {page_url}, test mode {test_mode}')
    if html:
      html = base64.b64decode(html).decode('utf-8')

    # boilerplate and save article in file
    if not title and not content:
      title, content, date = news_boilerplater(html=html, url=page_url, date=date)
    logging.info(f'title: {title}')
    logging.info(f'content: {content}')
    logging.info(f'date: {date}')
    if test_mode:
      return {'title': title, 'content': content, 'date': date, 'message': 'test_mode enabled'}

    # if there is content retrieved from the page
    if title is not None and content is not None and date is not None:
      try:
        html_ref = ''
        content_ref = ''
        is_translated = False
        unmatched_companies = False

        # translate text if necessary
        content_lang = check_language(content)
        if content_lang != 'en' and translate:
          if not is_text_in_english(title):
            title = translate_to_english(title)
          content = translate_to_english(content)
          is_translated = True

        # find sentences with company mentions
        company_to_description_dict = create_company_to_description_dict(companies=companies,
                                                                         title=title,
                                                                         content=content)

        try:
          # get named entities
          nes = get_company_nes_from_article(article="{}. {}".format(title, content)) if get_named_entities else None
          # if ner service didn't return an empty reponse and if article has entities
          if nes is not None:
            # get organization names
            organization_names = [i[0] for i in nes]
            logging.info("Named entities={}, organizations={}".format(nes, organization_names))

            # match them to DB
            matched_companies, matched_urls, matched_ids, company_mentions = match_nes_to_db_companies(
                named_entities=organization_names, hard_matching=False)
            logging.info("Linked company names={} with urls={}".format(matched_companies, matched_urls))

            if matched_companies and matched_urls and matched_ids and company_mentions:
              # save their article descriptions
              new_companies, company_to_description_dict = enrich_company_to_description_dict(
                  company_to_description_dict=company_to_description_dict,
                  company_mentions=company_mentions,
                  company_ids=matched_ids,
                  title=title,
                  content=content)
              # include them in `companies` and the company-article pairs later on in the DB
              companies = companies + new_companies
              unmatched_companies = [com for com in organization_names if com not in companies]
            else:
              logging.warning('Warning: No companies linked to our DB')
        except Exception as e:
          logging.error(f'Error getting named entities: {e}')

        # save data
        if companies:
          try:
            if html:
              html_ref = save_blob('news/html/' + clean_url(page_url), html)
            content_ref = save_blob('news/content/' + clean_url(page_url), content)
          except Exception as e:
            logging.error(f'Error saving to blob storage: {e}')

        company_article_match_found = False  # at least one match
        article_id_list = list()  # all article company pairs
        all_article_descriptions = list()
        all_product_article_descriptions = list()
        # try to fill the news tabs of the companies in our DB with this new article
        for company in companies:
          if company_to_description_dict[company["_id"]]:
            company_article_match_found = True
            printable_description = unidecode(company_to_description_dict[company["_id"]])
            all_article_descriptions.append(printable_description)
            data = {
                'title': title,
                'description': printable_description,
                'mentions': [company["name"]],
                'date': datetime.datetime.strptime(str(date), '%Y-%m-%d')
            }
            if is_translated:
              data['is_translated'] = is_translated
            if content_ref:
              data['content_ref'] = content_ref
            if html_ref:
              data['html_ref'] = html_ref
            if source:
              data['source'] = source
            if topic:
              data['topic'] = topic
            if content_lang:
              data['lang'] = content_lang
            article_id = db.news.update_one({
                'company_id': ObjectId(company['_id']),
                'url': page_url
            }, {'$set': data},
                                            upsert=True)

            if article_id.upserted_id:
              article_id_list.append(str(article_id.upserted_id))
              article_id = str(article_id.upserted_id)
              message += f'{page_url} added to DB.'
            else:
              message += f'{page_url} already exists.'
              article_id = str(db.news.find_one({'company_id': ObjectId(company['_id']), 'url': page_url})['_id'])

            # calling products service
            if not no_products:
              try:
                # TODO: move this outside the company iteration, it's the same for every company
                prod_data = {'article_id': str(article_id), 'title': title, 'content': content}
                url = 'https://api.delphai.live/delphai.products.Products.add_products'
                product_request = requests.post(url, json=prod_data)
                # if product_request:
                #   all_product_article_descriptions.append(product_request.text)
                # else:
                #   all_product_article_descriptions.append("")
                #   logging.info("Product detection model returned no text")
              except Exception as e:
                logging.error(f'Error getting product information: {e}')
                continue

        if unmatched_companies:
          data = {
              'title': title,
              'companies': list(set(unmatched_companies)),
              'date': datetime.datetime.strptime(str(date), '%Y-%m-%d')
          }
          if is_translated:
            data['is_translated'] = is_translated
          if content_ref:
            data['content_ref'] = content_ref
          if html_ref:
            data['html_ref'] = html_ref
          db.news_unmatched.update_one({'url': page_url}, {'$set': data}, upsert=True)

        if company_article_match_found:
          return {
              'article_ids': article_id_list,
              'title': title,
              'content': content,
              'descriptions': all_article_descriptions,
              'product_descriptions': all_product_article_descriptions,
              'message': f'Added {len(article_id_list)} company-article pairs to DB.'
          }
      except Exception as e:
        logging.error(f'Error: {e}')
        return {'title': title, 'content': content, 'message': f'Error: {e}'}
    if title is None:
      message += f'Article title is empty for the given url.'
    if content is None:
      message += f'Article content is empty for the given url.'
    if date is None:
      message += f'Article date is empty for the given url.'
    return {'message': message}

  except Exception as e:
    logging.error(f'Error: {e}')
    return {'message': f'Error: {e}'}
