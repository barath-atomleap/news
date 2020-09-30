import base64
import requests
import string
from bson import ObjectId
import datetime
from delphai_backend_utils.db_access import get_own_db_connection
from delphai_backend_utils.formatting import clean_url
from utils.utils import save_blob, is_text_in_english, translate_to_english
import logging
from news_processing import news_boilerplater, get_company_info_from_article, \
    get_company_nes_from_article, match_nes_to_db_companies

db = get_own_db_connection()
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


def save_articles(companies: list, page_url: str, html: str, test_mode: bool):
  """
  Receives a page from a news source, its html content and adds this news article to our DB.
  If a company from our DB is mentioned in this article, then the article is assigned to the company and it will
  appear in its news tab. Old implementation: If there is at least one mentioned company, then we also detect
  sentences in the text that discuss products and return the most relevant sentence.
  Args:
      companies: list of dictionaries with (_id, name) for each company
      page_url: url of the article
      html: html content of the article
      test_mode: return results instead of saving
  Returns: article ids in DB
  """
  try:
    message = ''
    logging.info(f'Saving article from {page_url} test mode {test_mode}')
    if html:
      html = base64.b64decode(html).decode('utf-8')

    # boilerplate and save article in file
    title, content, date = news_boilerplater(html=html, url=page_url)
    logging.info(f'test_mode: {test_mode}')
    logging.info(f'title: {title}')
    logging.info(f'content: {content}')
    if test_mode:
      return {'title': title, 'content': content}

    # if there is content retrieved from the page
    if title is not None and content is not None and date is not None:
      html_ref = ''
      content_ref = ''
      is_translated = False
      # translate text if necessary
      if not is_text_in_english(title):
        title = translate_to_english(title)
      if not is_text_in_english(content):
        content = translate_to_english(content)
        is_translated = True

      # save the company descriptions as they are discussed in the article
      company_to_description_dict = dict()
      if companies:
        # find fuzzy (98% of hard matching to deal with potential typos) mentions of the given companies in the article
        for company in companies:
          company_to_description_dict[company["_id"]] = get_company_info_from_article(company_name=company["name"],
                                                                         content="{}. {}".format(title, content))

      # get named entities
      nes = get_company_nes_from_article(article="{}. {}".format(title, content))
      # if ner service didn't return an empty reponse and if article has entities
      if nes is not None:
        # get company names
        organization_names = [i[0] for i in nes]
        # match them to DB
        matched_nes, matched_nes_urls, matched_nes_ids = match_nes_to_db_companies(named_entities=organization_names,
                                                    hard_matching=False)
        # combine given companies and discovered companies in the text
        for idx, matched_ne in enumerate(matched_nes):
          # if the discovered entities are not already given in `companies`
          if not any(matched_nes_ids[idx] in d for d in company_to_description_dict):
            company_dict = dict()
            company_dict["_id"] = matched_nes_ids[idx]
            company_dict["name"] = matched_ne
            # if a company is both in the `companies` list and in the `matched_nes` list, we keep this mention
            company_to_description_dict[company_dict["_id"]] = get_company_info_from_article(company_name=matched_ne,
                                                                                    content="{}. {}".format(title,
                                                                                                            content))
            companies.append(company_dict)

      if companies:
        try:
          html_ref = save_blob('news/html/' + clean_url(page_url), html)
          content_ref = save_blob('news/content/' + clean_url(page_url), content)
        except Exception as e:
          logging.error(f'Error saving to blob storage: {e}')

      company_article_match_found = False  # at least one match
      article_id_list = list()  # all article company pairs
      # make returned strings printable
      printable = set(string.printable)
      # try to fill the news tabs of the companies in our DB with this new article
      for company in companies:
        if company_to_description_dict[company["_id"]] != "":
          company_article_match_found = True
          printable_description = ''.join(filter(lambda ch: ch in printable, company_to_description_dict[company[
              "_id"]]))
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
          article_id = db.news.update_one({
              'company_id': ObjectId(company['_id']),
              'url': page_url
          }, {'$set': data},
                                          upsert=True)
          # article_id = db.news.insert_one(data)
          if article_id.upserted_id:
            article_id_list.append(str(article_id.upserted_id))
            article_id = str(article_id.upserted_id)
          else:
            message = 'Article already exists'
            article_id = str(db.news.find_one({'company_id': ObjectId(company['_id']), 'url': page_url})['_id'])

          # calling products service
          prod_data = {'article_id': str(article_id.inserted_id), 'title': title, 'content': content}
          # prod_data = {'article_id': article_id, 'title': title, 'content': content}
          url = 'https://api.delphai.live/delphai.products.Products.add_products'
          product_request = requests.post(url, json=prod_data)
          product_sentence = product_request.text
          printable_product_sentence = ''.join(filter(lambda ch: ch in printable, product_sentence))

      if company_article_match_found:
        return {'article_ids': article_id_list, 'title': title, 'content': content, 'message': message}

    return {'message': message}

  except Exception as e:
    logging.error(f'Error: {e}')
    return {'message': f'Error: {e}'}


def products_data(company_id, start_row, fetch_count):
  try:
    logging.info(f'Retrieving products for {company_id} page {start_row}')

    skip = (start_row - 1) * fetch_count

    news_articles = news.aggregate([{
        "$match": {
            "company_id": ObjectId(company_id),
            "prod_desc": {
                '$exists': 1
            }
        }
    }, {
        "$project": {
            "_id": 0,
            "description": '$prod_desc',
            "mentions": '$prod_mentions',
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
