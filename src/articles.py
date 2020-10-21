import base64
import requests
import string
from bson import ObjectId
import datetime
from delphai_backend_utils.db_access import get_own_db_connection
from delphai_backend_utils.formatting import clean_url
from utils.utils import save_blob, is_text_in_english, translate_to_english
import logging  # TODO: # use this instead: from delphai_backend_utils import logging
from news_processing import news_boilerplater, get_company_nes_from_article, match_nes_to_db_companies, get_company_info_from_article


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


def create_company_to_description_dict(companies: list, title: str, content: str):
  """
  Save the descriptions of the `companies` the way they are discussed in the article text. A description in
  this case is the text displayed in delphai under a url in the news tab.
  Args:
     companies: list of input companies to the service
     title: news article title
     content: news article body
  Returns: dict with keys the company ids and values the sentences that mention these companies in the text
  """

  company_to_description_dict = dict()
  if companies:
    for company in companies:
      try:
        company["_id"] = str(ObjectId(company["company"]))
      except:  # TODO: which exception is this?
        cmp = db.companies.find_one({'url': clean_url(company["company"])})
        if cmp:
          company["_id"] = str(cmp["_id"])
        else:
          continue
      company_to_description_dict[company["_id"]] = get_company_info_from_article(company_name=company["name"],
                                                                                  content="{}. {}".format(
                                                                                    title, content))
  return company_to_description_dict


def enrich_company_to_description_dict(company_to_description_dict: dict, companies: list, company_ids: list,
                                       title: str, content: str):
  """
  Combine given companies and discovered companies in the company_desc dict.
  Args:
    company_to_description_dict: the dict with the sentences that have company mentions
    companies: named entities that are discovered
    company_ids: the company ids of the named entities in our DB
    title: news article title
    content: news article body
  Returns: updated company_to_description_dict
  """
  new_companies = list()
  for idx, matched_ne in enumerate(companies):
    if (len(company_to_description_dict) > 0 and not any(company_ids[idx] in d for d in company_to_description_dict)) \
            or \
            (len(company_to_description_dict) == 0):
      company_dict = dict()
      company_dict["_id"] = company_ids[idx]
      company_dict["name"] = matched_ne
      company_to_description_dict[company_dict["_id"]] = get_company_info_from_article(
        company_name=matched_ne,
        content="{}. {}".format(
          title, content))
      new_companies.append(company_dict)
  return new_companies, company_to_description_dict


def save_articles(companies: list, page_url: str, html: str, test_mode: bool, date: str = ''):
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
      date: string with article date (optional)
  Returns: article ids in DB
  """
  try:
    message = ''
    logging.info(f'Saving article from {page_url}, test mode {test_mode}')
    if html:
      html = base64.b64decode(html).decode('utf-8')

    # boilerplate and save article in file
    title, content, date = news_boilerplater(html=html, url=page_url, date=date)
    logging.info(f'title: {title}')
    logging.info(f'content: {content}')
    if test_mode:
      return {'title': title, 'content': content}

    # if there is content retrieved from the page
    if title is not None and content is not None and date is not None:
      try:
        html_ref = ''
        content_ref = ''
        is_translated = False

        # translate text if necessary
        if not is_text_in_english(title):
          title = translate_to_english(title)
        if not is_text_in_english(content):
          content = translate_to_english(content)
          is_translated = True

        # find sentences with company mentions
        company_to_description_dict = create_company_to_description_dict(companies=companies, title=title,
                                                                         content=content)

        # get named entities
        nes = get_company_nes_from_article(article="{}. {}".format(title, content))
        # if ner service didn't return an empty reponse and if article has entities
        if nes is not None:
          # get company names
          organization_names = [i[0] for i in nes]

          # match them to DB
          matched_nes, matched_nes_urls, matched_nes_ids = match_nes_to_db_companies(
            named_entities=organization_names,
            hard_matching=False)

          # save their descriptions
          new_companies, company_to_description_dict = enrich_company_to_description_dict(
            company_to_description_dict=company_to_description_dict,
            companies=matched_nes,
            company_ids=matched_nes_ids,
            title=title,
            content=content)

          companies = companies + new_companies

        # save data
        if companies:
          try:
            html_ref = save_blob('news/html/' + clean_url(page_url), html)
            content_ref = save_blob('news/content/' + clean_url(page_url), content)
          except Exception as e:
            logging.error(f'Error saving to blob storage: {e}')

        company_article_match_found = False  # at least one match
        article_id_list = list()  # all article company pairs
        # make returned strings printable
        printable = set(string.printable)  # TODO: use better approach for this
        # try to fill the news tabs of the companies in our DB with this new article
        for company in companies:
          if company_to_description_dict[company["_id"]] != "":
            company_article_match_found = True
            printable_description = ''.join(
              filter(lambda ch: ch in printable, company_to_description_dict[company["_id"]]))
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

            article_id = db.news.insert_one(data)
            if article_id.upserted_id:
              article_id_list.append(str(article_id.upserted_id))
              article_id = str(article_id.upserted_id)
              message = f'{page_url} added to DB.'
            else:
              message = f'{page_url} already exists.'
              article_id = str(
                db.news.find_one({'company_id': ObjectId(company['_id']), 'url': page_url})['_id'])

            # calling products service
            try:
              prod_data = {'article_id': str(article_id.inserted_id), 'title': title, 'content': content}
              # prod_data = {'article_id': article_id, 'title': title, 'content': content}
              url = 'https://api.delphai.live/delphai.products.Products.add_products'
              product_request = requests.post(url, json=prod_data)
            except Exception as e:
              logging.error(f'Error getting product: {e}')
              return {'title': title, 'content': content, 'message': f'{message} Could not extract product info.'}

        if company_article_match_found:
          return {'article_ids': article_id_list, 'title': title, 'content': content,
                  'message': f'Added {len(article_id_list)} company-article pairs to DB.'}
      except Exception as e:
        logging.error(f'Error: {e}')
        return {'title': title, 'content': content, 'message': f'Error: {e}'}
    return {'message': f'Article content is empty for url={page_url}.'}

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

