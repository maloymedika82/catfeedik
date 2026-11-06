"""Offline GeoNames city centres. Public map positions never derive from feeding coordinates."""
from functools import lru_cache
import math
import geonamescache

@lru_cache(maxsize=1)
def catalogue():
    return geonamescache.GeonamesCache().get_cities()


def city_info(city_id):
    city=catalogue().get(str(city_id))
    if not city:
        return None
    return {'id':str(city['geonameid']),'name':city['name'],'country':city['countrycode'],
            'label':f"{city['name']}, {city['countrycode']}",
            'latitude':city['latitude'],'longitude':city['longitude']}


def nearest_city(latitude,longitude):
    def distance(city):
        a,b=math.radians(latitude),math.radians(city['latitude'])
        delta=math.radians(city['longitude']-longitude)
        return math.sin((b-a)/2)**2+math.cos(a)*math.cos(b)*math.sin(delta/2)**2
    closest=min(catalogue().values(),key=distance)
    return city_info(closest['geonameid'])
