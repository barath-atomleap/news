import trafilatura
from cleantext import clean
import re
import nltk
from fuzzywuzzy import fuzz
from ktrain import text


def news_boilerplater(html: str):
  """
  Receives a web page from a news source with `html` contents.
  Returns the title, text content and publication date of this news entry.
  Args:
      html: string with all html code of this page
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
    try:
      text = text.encode('latin-1').decode('unicode_escape')
    except Exception as e:
      print("{}: Can't perform encoding and decoding on news article text. Keeping the original text.", str(e))
      text = text
    text = re.sub("\s+", " ", text)
    return text.strip()

    page_content = trafilatura.extract(html)
    page_metadata = trafilatura.metadata.extract_metadata(html)
    article_publication_date = page_metadata.date
    article_title = preprocess_text(str(page_metadata.title))
    page_content = preprocess_text(str(page_content))
    return article_title, page_content, article_publication_date


def get_company_info_from_article(company_name: str, content: str):
  """
    Checks if company with `company_name` appears in text `content`, using the fuzzy wuzzy package.
    :param content: text in a news article (str)
    :param company_name: company name (str)
    :return: str: first sentence that the company name appears in
    """
  # if the given article mentions the given company
  if fuzz.partial_token_set_ratio(company_name, content) > 90:
    # return the first text snippet that contains company information
    for sentence in nltk.sent_tokenize(content):
      if fuzz.partial_token_set_ratio(company_name, sentence) > 90:
        return sentence
  else:
    return None


def get_product_info_from_article(content: str, keywords: list):
  """
    Given the text `content` of a news article, tokenizes it in sentences and computes the similarity of the text to
    predefined keywords `keywords` that are related to product launches.
    :param keywords: list of words related to company products (list of str)
    :param content: article text (str)
    :return: str: most relevant sentence
    """

  zeroshotclassifier = text.ZeroShotClassifier()  # unsupervised deep learning model for topic classification

  relevant_sentences = []
  # tokenize the article into sentences and find which sentences contain product information
  for sentence in nltk.sent_tokenize(content):
    prediction = zeroshotclassifier.predict(doc=sentence, topic_strings=keywords, include_labels=True)
    score = prediction[0][-1]
    if score > 0.90:
      relevant_sentences.append([sentence, prediction])
  # sort sentences based on their similarity score to product keywords
  relevant_sentences = [x[0] for x in sorted(relevant_sentences, key=lambda x: x[1], reverse=True)]

  if len(relevant_sentences) == 0:
    return None
  else:
    # return the most relevant text snippet
    return relevant_sentences[0]
