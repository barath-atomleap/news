import trafilatura
from cleantext import clean
import re
import nltk
from fuzzywuzzy import fuzz
nltk.download('punkt')


def news_boilerplater(html: str = '', url: str = ''):
  """
  Receives a web page from a news source with `html` contents.
  Returns the title, text content and publication date of this news entry.
  Args:
      html: string with all html code of this page
      url: string with article url to be scraped
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

  page_content = trafilatura.extract(html, include_comments=False, include_tables=False)
  if page_content is not None:
    page_content = preprocess_text(str(page_content))
    page_metadata = trafilatura.metadata.extract_metadata(html)
    if page_metadata is not None:
      article_publication_date = page_metadata.date
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
  if fuzz.token_set_ratio(company_name.lower(), content) > 98:
    # return the first text snippet that contains company information
    for sentence in nltk.sent_tokenize(content):
      if fuzz.token_set_ratio(company_name.lower(), sentence) > 98:
        return sentence
  else:
    return ""
