#!/bin/bash
# tools/fetch_comps.sh
# Usage: ./fetch_comps.sh "Rhinebeck, NY" "3" "4"

LOCATION=$1
BEDS_MIN=$2
BEDS_MAX=$3
STATUS=$4

if [ -z "$RAPIDAPI_KEY" ]; then
    echo "Error: RAPIDAPI_KEY environment variable is not set."
    exit 1
fi

URL="https://real-time-real-estate-data.p.rapidapi.com/search?location=${LOCATION// /%20}&beds_min=$BEDS_MIN&beds_max=$BEDS_MAX"

if [ ! -z "$STATUS" ]; then
    URL="${URL}&home_status=$STATUS"
fi

curl --silent --request GET \
       --max-time 15 \
       --url "$URL" \
       --header "x-rapidapi-host: real-time-real-estate-data.p.rapidapi.com" \
       --header "x-rapidapi-key: $RAPIDAPI_KEY"

