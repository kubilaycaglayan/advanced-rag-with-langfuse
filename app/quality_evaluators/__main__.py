import argparse
import json
from . import reconcile

parser = argparse.ArgumentParser()
parser.add_argument('--write', action='store_true')
print(json.dumps(reconcile(parser.parse_args().write), indent=2))
