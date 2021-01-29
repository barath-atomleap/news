from delphai_utils.formatting import clean_url
import trafilatura
from newspaper import Article, fulltext
from bson import ObjectId
from cleantext import clean
from cleanco import prepare_terms, basename
import base64
import re
import nltk
from fuzzywuzzy import fuzz
import json
import requests
import httpx
from proto.proto.names_matcher_pb2_grpc import NamesMatcherStub
from proto.proto.names_matcher_pb2 import NamesMatchRequest, NamesMatchResponse
from delphai_utils.logging import logging
from delphai_utils.db import db
from delphai_utils.config import get_config
from grpc.experimental.aio import insecure_channel

nltk.download('punkt')

post_retry_times = 5
names_matcher_address = get_config('names_matcher.address')
channel = insecure_channel(names_matcher_address)
nel_client = NamesMatcherStub(channel)


async def news_boilerplater(html: str = '', url: str = '', date: str = ''):
  """
  Receives a web page from a news source with `html` contents.
  Returns the title, text content and publication date of this news entry.
  Args:
      html: string with all html code of this page
      url: string with article url to be scraped
      date: string with article date (optional)
  Returns:
      title (str), content (str), publication_date (str)
  """
  def preprocess_text(text: str):
    """
    Cleaning and processing text extracted from web page with trafilatura.
    :param text: input string with text
    :return: clean text
    """

    text = text.strip()
    try:
      text = clean(text)
    except Exception as e:
      logging.error("{}: Can't preprocess news article text with cleantext package. Keeping the original text.", str(e))
      text = text
    text = re.sub(pattern="\s+", repl=" ", string=text)
    return text.strip()

  if not html and url:
    async with httpx.AsyncClient() as client:
      html = (await client.get(url)).text
      if not html:
        single_scraper_url = get_config('single_scraper.url')
        response = await client.post(single_scraper_url, json={'url': url})
        html = base64.b64decode(response.json()['html']).decode('utf-8')

    # html = trafilatura.fetch_url(url)
    # if not html:
    #   data = {'url': url}
    #   url = get_config('single_scraper.url')
    #   x = requests.post(url, json=data)
    #   html = base64.b64decode(x.json()['html']).decode('utf-8')

  # logging.info(f'html after: {len(html) if html else html}')
  page_content = trafilatura.extract(html, include_comments=False, include_tables=False)
  article = Article(url=url)
  article.download(input_html=html)
  article.parse()
  # logging.info(f'page_content: {page_content}')
  if page_content is not None:
    page_content = preprocess_text(str(page_content))
    page_metadata = trafilatura.metadata.extract_metadata(html)
    if page_metadata is not None:
      try:
        article_publication_date = page_metadata["date"]
        if not article_publication_date:
          article_publication_date = date if date else None
      except Exception as e:
        logging.error(f'no date found for {url}:', e)
        article_publication_date = date if date else None
      if not article_publication_date:
        article_publication_date = article.publish_date
      try:
        article_title = preprocess_text(str(page_metadata["title"]))
      except Exception as e:
        logging.error(f'no title found for {url}:', e)
        article_title = article.title
      return article_title, page_content, article_publication_date, html
    else:
      article_title = article.title
      article_publication_date = article.publish_date
      return article_title, page_content, article_publication_date, html
  else:
    article_title = article.title
    article_publication_date = article.publish_date
    page_content = article.text
    return article_title, page_content, article_publication_date, html


def get_company_info_from_article(company_name: str, content: str):
  """
  Checks if company with `company_name` appears in text `content`, using the fuzzy wuzzy package.
  :param content: text in a news article (str)
  :param company_name: company name (str)
  :return: str: first sentence that the company name appears in
  """
  # if the given article mentions the given company
  if fuzz.token_set_ratio(company_name, content) > 98:
    # return the first text snippet that contains company information
    for sentence in nltk.sent_tokenize(content):
      if fuzz.token_set_ratio(company_name, sentence) > 98:
        return sentence
  else:
    return ""


async def get_company_nes_from_article(article: str):
  """
  Given a news article, it returns the company mentions identified as named entities.
  :param article: body of news article
  :return: dictionary with organizations discovered by spacy
  """
  scoring_uri = get_config('english_ner.uri')
  key = get_config('english_ner.key')
  input_data = json.dumps(article)
  # Set the content type and authorization
  headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'}
  async with httpx.AsyncClient() as client:
    for i in range(0, post_retry_times):
      try:
        # resp = requests.post(scoring_uri, input_data, headers=headers)
        resp = await client.post(scoring_uri, input_data, headers=headers)
        mention_dict = json.loads(resp.text)  # contains mentions of organizations, locations and persons
        logging.info(f'Mentions dict:{mention_dict}')
        return mention_dict['ORG']
      except json.decoder.JSONDecodeError as e:
        logging.error(f"Calling the NER service caused an error: {e}. Retrying to do the post request another time.")

  return None


async def get_company_nes_from_ger_article(article: str):
  """
  Given a german news article, it returns the company mentions identified as named entities.
  :param article: body of german news article
  :return: dictionary with organizations discovered by spacy
  """
  scoring_uri = get_config('german_ner.uri')
  key = get_config('german_ner.key')
  input_data = json.dumps(article)
  # Set the content type and authorization
  headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'}
  async with httpx.AsyncClient() as client:
    for i in range(0, post_retry_times):
      try:
        # resp = requests.post(scoring_uri, input_data, headers=headers)
        resp = await client.post(scoring_uri, input_data, headers=headers)
        mention_dict = json.loads(resp.text)  # contains mentions of organizations, locations and persons
        return mention_dict['ORG']
      except json.decoder.JSONDecodeError as e:
        logging.error(
            f"Calling the German NER service caused an error: {e}. Retrying to do the post request another time.")
  return None


async def match_nes_to_db_companies(named_entities: list, hard_matching: bool):
  """
    Given a list of organizations discovered in the text with the named entity recognizer, match them to our DB and
    find the corresponding companies by name and url.
    :param hard_matching: if this is True, due to duplicates in the db, we only match strictly when the two companies
     have exactly the same name
    :param named_entities: list of organizations discovered in the text
    """
  def get_names_of_matches(best_matches: dict):
    """
        Get company names from the response of the name macther
        :param best_matches: dict with matches between company mentions in the news to the companies in the db
        :return: list of company mentions with high confidence
        """
    company_mentions = list()
    matched_companies = list()
    urls = list()
    company_ids = list()

    # find pairs of hard matches
    for mentioned_organization in best_matches:
      # TODO: check if there is more than one match with the exact name in the DB, like "Superior" and "Superior
      #  Industries" have two entries in the DB
      company_in_db = best_matches[mentioned_organization]["best"]["name"]
      url_in_db = best_matches[mentioned_organization]["best"]["url"]
      id_in_db = best_matches[mentioned_organization]["best"]["id"]
      if hard_matching:
        if mentioned_organization == company_in_db:
          matched_companies.append(company_in_db)
          company_mentions.append(mentioned_organization)
          urls.append(url_in_db)
          company_ids.append(id_in_db)
      else:
        matched_companies.append(company_in_db)
        company_mentions.append(mentioned_organization)
        urls.append(url_in_db)
        company_ids.append(id_in_db)
    return matched_companies, urls, company_ids, company_mentions

  # clean nes
  terms = prepare_terms()
  clean_named_entities = list()
  for company in named_entities:
    clean_named_entities.append(basename(company, terms, prefix=False, middle=False, suffix=True))
  # reduce calculations of the name matcher
  all_entities = list(set(named_entities + clean_named_entities))
  # TODO: check if company names are included in each other like Maxion inside Maxion Wheels
  # NOTE: test if industry or embeddings can help with the resolution of such cases
  # match nes to DB
  for i in range(0, post_retry_times):
    try:
      # logging.info("Name matcher input: {}".format(all_entities))
      req = NamesMatchRequest(names=all_entities)
      ner_matching_response: NamesMatchResponse = await nel_client.match(req)
      ner_matching_response = ner_matching_response.results if ner_matching_response.results else []

      # ner_matching_response = requests.post(get_config('nel.url'), json={'names': all_entities}).json()
      # add name matching results to dict and filter them
      ner_best_matches = {
          r['name']: {
              'count': r['matches_count'],
              'best': r['matches'][0]
          }
          for r in ner_matching_response
      }

      logging.info('Matcher response:')
      for result in ner_matching_response:
        logging.info(result)
      if ner_best_matches:
        # get company names from dict
        matched_names, matched_urls, matched_ids, company_mentions = get_names_of_matches(best_matches=ner_best_matches)
        if matched_names:
          return matched_names, matched_urls, matched_ids, company_mentions
      return None, None, None, None
    except json.decoder.JSONDecodeError as e:
      logging.error(f'Error: from our NamesMatcher service: {e}')
  return None, None, None, None


async def create_company_to_descr_dict(companies: list, title: str, content: str):
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
      except:  # if "company" is not ObjectId, search for url
        cmp = await db.companies.find_one({'url': clean_url(company["company"])})
        if cmp:
          company["_id"] = str(cmp["_id"])
        else:
          continue
      company_to_description_dict[company["_id"]] = get_company_info_from_article(company_name=company["name"],
                                                                                  content="{}. {}".format(
                                                                                      content, title))
  return company_to_description_dict


def enrich_company_to_descr_dict(company_to_descr_dict: dict, company_mentions: list, company_ids: list, title: str,
                                 content: str):
  """
  Combine given companies and discovered companies in the company_desc dict.
  Args:
    company_mentions: named entities that are discovered
    company_to_descr_dict: the dict with the sentences that have company mentions
    company_ids: the company ids of the named entities in our DB
    title: news article title
    content: news article body
  Returns: updated company_to_description_dict
  """
  new_companies = list()
  for idx, company_mention in enumerate(company_mentions):
    if (len(company_to_descr_dict) > 0 and not any(company_ids[idx] in d for d in company_to_descr_dict)) \
            or \
            (len(company_to_descr_dict) == 0):
      company_dict = dict()
      company_dict["_id"] = company_ids[idx]
      company_dict["name"] = company_mention
      company_to_descr_dict[company_dict["_id"]] = get_company_info_from_article(company_name=company_mention,
                                                                                 content="{}. {}".format(
                                                                                     content, title))
      new_companies.append(company_dict)
  return new_companies, company_to_descr_dict
