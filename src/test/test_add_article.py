from typing import Dict, List, Tuple
from services.news import add_article
import pytest
from proto.news_pb2 import AddArticleRequest, AddArticleResponse
from pytest_snapshot.plugin import Snapshot
from test.conftest import process_snapshot, get_test_urls

test_urls = get_test_urls(3)


@pytest.mark.asyncio
@pytest.mark.parametrize('input', test_urls)
async def test_add_article(input: str, snapshot: Snapshot):
  result = await add_article(AddArticleRequest(url=input))
  assert isinstance(result, AddArticleResponse)
  process_snapshot(input, snapshot, result)
