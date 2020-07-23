from bson import ObjectId
import datetime
from delphai_backend_utils.db_access import get_own_db_connection
from utils.utils import clean_url, save_blob
import logging

db = get_own_db_connection()
articles = db.articles
articles.create_index('url', unique=True)
articles.create_index('company_id')


def articles_data(company_id, start_row, fetch_count):

  skip = (start_row - 1) * fetch_count

  news_articles = articles.aggregate([{
      "$match": {
          "company_id": ObjectId(company_id)
      }
  }, {
      "$project": {
          "_id": 0,
          "description": 1,
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


def save_articles(company_url, page_url, html, date):
  try:
    company = db.companies.find_one({'url': clean_url(company_url)}, {'url': 1})
    text, title, description = html, 'title', 'scope'  # 'boilerplating(html)'
    html_ref = save_blob('articles/' + clean_url(page_url), html)
    date = datetime.datetime.strptime(str(date), '%Y-%m-%d')
    data = {
        'company_id': company['_id'],
        'url': page_url,
        'text': text,
        'title': title,
        'description': description,
        'html_ref': html_ref,
        'date': date  #  datetime.datetime.now()
    }

    article_id = articles.insert_one(data)

    # article_id = article.update_one(new_page.to_native(role='query'), {'$set': new_page.to_native(role='set')},
    #                                    upsert=True)
    return str(article_id.inserted_id)

  except Exception as e:
    logging.error(f'Error: {e}')
