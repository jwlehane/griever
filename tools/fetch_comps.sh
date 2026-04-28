#!/bin/bash
# tools/fetch_comps.sh
# Usage: ./fetch_comps.sh "Rhinebeck, NY" "3" "4"

LOCATION=$1
BEDS_MIN=$2
BEDS_MAX=$3

if [ -z "$RAPIDAPI_KEY" ]; then
    echo "Error: RAPIDAPI_KEY environment variable is not set."
    exit 1
fi

# Note: The new API uses 'location' instead of separate city/state
# and 'status' can be set to 'recently_sold' or similar if supported.
# We'll use the /search endpoint as identified.

curl --silent --request GET \
	--url "https://real-time-real-estate-data.p.rapidapi.com/search?location=${LOCATION// /%20}&beds_min=$BEDS_MIN&beds_max=$BEDS_MAX&status=FOR_SALE" \
	--header "x-rapidapi-host: real-time-real-estate-data.p.rapidapi.com" \
	--header "x-rapidapi-key: $RAPIDAPI_KEY"
