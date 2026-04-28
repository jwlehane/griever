#!/bin/bash
# tools/fetch_comps.sh
# Usage: ./fetch_comps.sh "Rhinebeck" "NY" "3" "4"

CITY=$1
STATE=$2
BEDS_MIN=$3
BEDS_MAX=$4

if [ -z "$RAPIDAPI_KEY" ]; then
    echo "Error: RAPIDAPI_KEY environment variable is not set."
    exit 1
fi

curl --silent --request GET \
	--url "https://real-estate-data.p.rapidapi.com/properties/v2/list-for-sale?city=$CITY&state_code=$STATE&beds_min=$BEDS_MIN&beds_max=$BEDS_MAX&status=recently_sold" \
	--header "x-rapidapi-host: real-estate-data.p.rapidapi.com" \
	--header "x-rapidapi-key: $RAPIDAPI_KEY"
