import sys
from typing import List

from pytest_snapshot.plugin import Snapshot
sys.path.append('./src')
sys.path.append('./src/proto')

import asyncio
import pytest
from google.protobuf.json_format import MessageToDict
import yaml
import csv
import os
import ast


def get_test_urls(limit: int = None):
  dirname = os.path.dirname(__file__)
  test_urls: List[str] = []
  with open(f'{dirname}/data/chiron.csv', 'r') as chiron_urls_file:
    reader = csv.reader(chiron_urls_file)
    next(reader, None)
    for row in reader:
      test_urls.append(row[2])
  return test_urls[:limit] if limit else test_urls


def process_snapshot(input: str, snapshot: Snapshot, result):
  url_split = input.rstrip('/').replace('http://', '').replace('https://', '').split('/')
  dir_name = '/'.join(url_split[:-1])
  file_name = url_split[-1]
  snapshot.snapshot_dir = f'.snapshots/{dir_name}'
  processed_result = MessageToDict(result, preserving_proto_field_name=True)
  content: str = processed_result['content']
  processed_result['url'] = input
  snapshot.assert_match(content, f'{file_name}.md')
  del processed_result['content']
  if 'translated_content' in processed_result:
    snapshot.assert_match(processed_result['translated_content'], f'{file_name}-en.md')
    del processed_result['translated_content']
  snapshot.assert_match(yaml.dump(processed_result, default_flow_style=False, allow_unicode=True), f'{file_name}.yml')


@pytest.yield_fixture(scope='session')
def event_loop(request):
  """Create an instance of the default event loop for each test case."""
  loop = asyncio.get_event_loop()
  yield loop
  loop.close()