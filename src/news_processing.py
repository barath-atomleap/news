import trafilatura
from cleantext import clean
import re
from datetime import date


def news_boilerplater(html: str):
  """
    Receives a web page from a news source with `html` contents.
    Returns the title, text content and publication date of this news entry.
    Args:
        html: string with all html code of this page
    Returns:
        title (str), content (str), publication_date (datetime.date)
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
      print("Can't preprocess news article text with cleantext package:", str(e))
      # print("Article text:\n{}".format(text))
      text = text
    try:
      text = text.encode('latin-1').decode('unicode_escape')
    except Exception as e:
      print("Can't perform encoding and decoding on news article text:", str(e))
      # print("Article text:\n{}".format(text))
      text = text

    text = re.sub("\s+", " ", text)
    return text.strip()

  # for testing
  # html = trafilatura.fetch_url(html)
  # print('got html', len(html))

  page_content = trafilatura.extract(html)
  page_metadata = trafilatura.metadata.extract_metadata(html)
  article_publication_date = page_metadata.date
  article_title = preprocess_text(str(page_metadata.title))
  page_content = preprocess_text(str(page_content))

  return article_title, page_content, article_publication_date
