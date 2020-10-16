import trafilatura
from cleantext import clean
from cleanco import prepare_terms, basename
import base64
import re
import nltk
from fuzzywuzzy import fuzz
import json
import requests
import logging
nltk.download('punkt')

post_retry_times = 5


def news_boilerplater(html: str = '', url: str = '', date: str = ''):
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
      print("{}: Can't preprocess news article text with cleantext package. Keeping the original text.", str(e))
      text = text
    text = re.sub(pattern="\s+", repl=" ", string=text)
    return text.strip()

  if not html and url:
    html = trafilatura.fetch_url(url)
    if not html:
      data = {'url': url}

      url = 'https://delphai-source-scraper.azurewebsites.net/api/scrape-single-url'
      x = requests.post(url, json=data)
      html = base64.b64decode(x.json()['html']).decode('utf-8')

  page_content = trafilatura.extract(html, include_comments=False, include_tables=False)
  if page_content is not None:
    page_content = preprocess_text(str(page_content))
    page_metadata = trafilatura.metadata.extract_metadata(html)
    if page_metadata is not None:
      try:
        article_publication_date = page_metadata.date
      except Exception as e:
        logging.error('no date found:', e)
        article_publication_date = date if date else None
      article_title = preprocess_text(str(page_metadata.title))
      return article_title, page_content, article_publication_date
    else:
      return None, page_content, None
  else:
    return None, page_content, None


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


def get_company_nes_from_article(article: str):
  """
  Given a news article, it returns the company mentions identified as named entities.
  :param article: body of news article
  :return: dictionary with organizations discovered by spacy
  """
  scoring_uri = 'http://51.145.149.205:80/api/v1/service/article-tagger/score'
  key = 'aaEpe1OxRyWTDuSNdvzKxsrFdKWQbhh6'
  input_data = json.dumps(article)
  # Set the content type and authorization
  headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'}
  for i in range(0, post_retry_times):
    try:
      resp = requests.post(scoring_uri, input_data, headers=headers)
      mention_dict = json.loads(resp.text)  # contains mentions of organizations, locations and persons
      return mention_dict['ORG']
    except json.decoder.JSONDecodeError as e:
      logging.error(f"Calling the NER service caused an error: {e}. Retrying to do the post request another time.")
  return None


def match_nes_to_db_companies(named_entities: list, hard_matching: bool):
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
    entities_to_keep = list()
    entities_urls = list()
    entities_ids = list()
    # find pairs of hard matches
    for mentioned_organization in best_matches:
      # TODO: check if there is more than one match with the exact name in the DB, like "Superior" and "Superior
      #  Industries" have two entries in the DB
      company_in_db = best_matches[mentioned_organization]["best"]["name"]
      url_in_db = best_matches[mentioned_organization]["best"]["url"]
      id_in_db = best_matches[mentioned_organization]["best"]["id"]
      if hard_matching:
        if mentioned_organization == company_in_db:
          entities_to_keep.append(company_in_db)
          entities_urls.append(url_in_db)
          entities_ids.append(id_in_db)
      else:
        entities_to_keep.append(company_in_db)
        entities_urls.append(url_in_db)
        entities_ids.append(id_in_db)
    return entities_to_keep, entities_urls, entities_ids

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
      ner_matching_response = requests.post('https://api.delphai.live/delphai.namesmatcher.NamesMatcher.match',
                                            json={
                                                'names': all_entities
                                            }).json()
      # add name matching results to dict and filter them
      ner_best_matches = {
          r['name']: {
              'count': r['matches_count'],
              'best': r['matches'][0]
          }
          for r in ner_matching_response.get('results', [])
      }
      # get company names from dict
      matched_names, matched_urls, matched_ids = get_names_of_matches(best_matches=ner_best_matches)
      return matched_names, matched_urls, matched_ids
    except json.decoder.JSONDecodeError as e:
      logging.error(f'Error: from our NamesMatcher service: {e}')
  return None
