#!/bin/bash

fastapi run --port 8000 --host 0.0.0.0 & 
litellm --config ./config.yaml --port 7800 --host 0.0.0.0 &

wait
