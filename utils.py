import unicodedata
import re


def slugify (s):
    s = s.replace(' ', '_').lower()
    print (type(s), s)
    if type(s) is str:
        slug = unicodedata.normalize('NFKD', s)
    elif type(s) is str:
        slug = s
    else:
        raise AttributeError("Can't slugify string")
    slug = str(slug.encode('ascii', 'ignore'))
    #slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')
    #slug = re.sub(r'--+',r'-',slug)
    print (type(slug), slug)
    return slug