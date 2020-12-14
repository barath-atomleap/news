import base64
import requests
from unidecode import unidecode
from bson import ObjectId
import datetime
from delphai_utils.formatting import clean_url
from utils.utils import check_language, save_blob, is_text_in_english, translate_to_english
from delphai_utils.logging import logging
from delphai_utils.db import db_sync
from .news_processing import create_company_to_descr_dict, enrich_company_to_descr_dict
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
                 add_only_english: bool = False):
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
      add_only_english: add only articles in English
  Returns: article ids in DB
  """

  def create_data_object(title, description, mentions, date, is_translated, content_ref, original_content_ref,
                         html_ref, source, topic, lang, unmatched_companies):
    """
    Create object to ingest to the news db collection.
    """
    data = dict()
    if title:
      data['title'] = title
    else:
      logging.error('Trying to add a news article with empty title to the db.')
    if date:
      data['date'] = date
    else:
      logging.error('Trying to add a news article with empty date to the db.')
    if description:
      data['description'] = description
    if mentions:
      data['mentions'] = mentions
    if is_translated:
      data['is_translated'] = is_translated
    if content_ref:
      data['content_ref'] = content_ref
    if original_content_ref:
      data['original_content_ref'] = original_content_ref
    if html_ref:
      data['html_ref'] = html_ref
    if source:
      data['source'] = source
    if topic:
      data['topic'] = topic
    if lang:
      data['lang'] = lang
    if unmatched_companies:
      data['companies'] = unmatched_companies
    return data

  try:
    message = ''
    content_lang = ''
    logging.info(f'Saving article from {page_url}, test mode {test_mode}')
    # our scraper feeders provide html, but the external news datasets are already boilerplated
    if html:
      html = base64.b64decode(html).decode('utf-8')

    # if not boilerplated input, process and boilerplate article
    if not title and not content:
      title, content, date = news_boilerplater(html=html, url=page_url, date=date)
    logging.info(f'Title={title}, Content={content[:100]} ... , Date={date}')
    if test_mode:
      return {'title': title, 'content': content, 'date': date, 'message': 'test_mode enabled'}

    # if there is content retrieved from the article page
    if title is not None and content is not None and date is not None:
      try:
        html_ref = content_ref = original_content_ref = ''
        original_content = ''
        is_translated = False
        unmatched_companies = False

        # translate text if necessary
        content_lang = check_language(content)
        if content_lang != 'en':
          if add_only_english:
            return {'title': title, 'content': content, 'date': date, 'message': 'Article not in English'}
          title = translate_to_english(title)
          original_content = content
          content = translate_to_english(content)
          is_translated = True

        # find sentences with input company mentions. if companies are given then we assume they will appear in the text
        company_to_descr_dict = create_company_to_descr_dict(companies=companies, title=title, content=content)

        # link input and discovered companies to our company database
        try:
          # get named entities
          nes = get_company_nes_from_article(article="{}. {}".format(title, content)) if get_named_entities else None
          # if ner service didn't return an empty reponse and if article has entities
          if nes is not None:
            # get organization names
            organization_names = [i[0] for i in nes]
            logging.info(f"Named entities={nes}, Organizations={organization_names}")
            # match them to DB
            matched_companies, matched_urls, matched_ids, company_mentions = match_nes_to_db_companies(
              named_entities=organization_names, hard_matching=False)
            # if matching linked at least one company to our database
            if matched_companies and matched_urls and matched_ids and company_mentions:
              logging.info(f"Linked company names={matched_companies} with urls={matched_urls}")
              # find the mentions of the companies discovered by ner
              new_companies, company_to_descr_dict = enrich_company_to_descr_dict(
                company_to_descr_dict=company_to_descr_dict,
                company_mentions=company_mentions,
                company_ids=matched_ids,
                title=title,
                content=content)
              # include them in `companies` and the company-article pairs later on in the DB
              logging.info(f'input companies:{companies}')
              companies = companies + new_companies
              logging.info(f'new_companies:{new_companies}')
              unique_organization_names = set(organization_names)
              unmatched_companies = [org for org in unique_organization_names if not(any(com['name'] == org for com in
                                                                                companies))]
              logging.info(f'unmatched_companies:{unmatched_companies}')
              logging.info(f'matched companies:{companies}')
              message += f'Adding article to {len(new_companies)} more companies in delphai ({new_companies}).\n'
            else:
              logging.warning('Warning: No companies linked to our DB')
        except Exception as e:
          logging.error(f'Error getting named entities: {e}')
          message += 'Either the named entity recognition or linking service is not responding.\n'

        # save html and text, only if the article contains company mentions
        if companies:
          try:
            if html:
              html_ref = save_blob('news/html/' + clean_url(page_url), html)
            content_ref = save_blob('news/content/' + clean_url(page_url), content)
            if original_content:
              original_content_ref = save_blob('news/original_content/' + clean_url(page_url), original_content)
          except Exception as e:
            logging.error(f'Error saving to blob storage: {e}')

        # save article company pairs to the companies db collection
        company_article_match_found = False  # at least one match
        article_id_list = list()  # all article company pairs
        all_article_descriptions = list()
        all_product_article_descriptions = list()
        for company in companies:
          if company_to_descr_dict[company["_id"]]:
            company_article_match_found = True
            printable_description = unidecode(company_to_descr_dict[company["_id"]])
            all_article_descriptions.append(printable_description)
            data = create_data_object(title=title,
                                      description=printable_description,
                                      mentions=[company["name"]],
                                      date=datetime.datetime.strptime(str(date), '%Y-%m-%d'),
                                      is_translated=is_translated,
                                      content_ref=content_ref,
                                      original_content_ref=original_content_ref,
                                      html_ref=html_ref,
                                      source=source,
                                      topic=topic,
                                      lang=content_lang,
                                      unmatched_companies=[])
            article_id = db.news.update_one({
              'company_id': ObjectId(company['_id']),
              'url': page_url
            }, {'$set': data},
              upsert=True)

            if article_id.upserted_id:
              article_id_list.append(str(article_id.upserted_id))
              article_id = str(article_id.upserted_id)
              message += f'{page_url} added to DB.\n'
            else:
              message += f'{page_url} already exists.\n'
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
          else:
            message += 'Company name not found in article.\n'

        # add newly discovered company names that could not be linked to our db in a separate db collection
        if unmatched_companies:
          data = create_data_object(title=title,
                                    description='',
                                    mentions=[],
                                    date=datetime.datetime.strptime(str(date), '%Y-%m-%d'),
                                    is_translated=is_translated,
                                    content_ref=content_ref,
                                    original_content_ref=None,
                                    html_ref=html_ref,
                                    source='',
                                    topic='',
                                    lang='',
                                    unmatched_companies=list(set(unmatched_companies)))
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
