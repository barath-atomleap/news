import base64
from bson import ObjectId
import datetime
from delphai_backend_utils.db_access import get_own_db_connection
from delphai_backend_utils.formatting import clean_url
from utils.utils import save_blob, is_text_in_english, translate_to_english
import logging
from news_processing import news_boilerplater, get_company_info_from_article

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
      companies: list of dictionaries with (_id, name, url) for each company
      page_url: url of the article
      html: html content of the article
      test_mode: return results instead of saving
  Returns: article ids in DB
  """
  try:
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
      is_translated = False
      # translate text if necessary
      if not is_text_in_english(title):
        title = translate_to_english(title)
      if not is_text_in_english(content):
        content = translate_to_english(content)
        is_translated = True

      # name entity recognition
      # companies = companies + [NER stuff]

      if companies:
        html_ref = save_blob('news/html/' + clean_url(page_url), html)
        content_ref = save_blob('news/content/' + clean_url(page_url), content)

      company_article_match_found = False  # at least one match
      article_id_list = list()  # all article company pairs

      # try to fill the news tabs of the companies in our DB with this new article
      for company in companies:
        news_snippet_about_company = get_company_info_from_article(company_name=company["name"],
                                                                   content="{}. {}".format(title, content))
        if news_snippet_about_company != "":
          company_article_match_found = True
          data = {
              'company_id': company['_id'],
              'url': page_url,
              'content_ref': content_ref,
              'title': title,
              'description': news_snippet_about_company,
              'mentions': [company["name"]],
              'html_ref': html_ref,
              'date': datetime.datetime.strptime(str(date), '%Y-%m-%d')
          }
          if is_translated:
            data['is_translated'] = is_translated
          article_id = db.news.insert_one(data)
          article_id_list.append(str(article_id.inserted_id))

          # TODO: call products service
          import requests
          prod_data = {'article_id': str(article_id.inserted_id), 'title': title, 'content': content}
          url = 'https://api.delphai.live/delphai.validation.Validation.validate'
          x = requests.post(url, json=prod_data)
          results = x.json()
          # print(results)

      if company_article_match_found:
        return {'article_ids': article_id_list, 'title': title, 'content': content}

    return {}

  except Exception as e:
    logging.error(f'Error: {e}')
    return {}


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
