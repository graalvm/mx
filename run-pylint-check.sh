#!/bin/bash

set -e
set -u
set -o pipefail

echo "python version: $(python --version)"
./mx --strict-compliance gate --strict-mode

if [[ $? == 0 ]]; then
  echo "Fix the issue reported above before pushing the commit or creating a PR"
fi