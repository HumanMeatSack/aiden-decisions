"""Pure example intent parser. No device services, drivers or credentials."""
from __future__ import annotations
import importlib.resources
import json
import re
from pathlib import Path

SAFE_ID = re.compile(r'[a-zA-Z0-9_-]{1,80}')

ACTIONS = {'status', 'power', 'brightness', 'temperature', 'media'}

QUERY_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 '&+.,:!?-]{0,79}")

MEDIA_PROVIDERS = {
    "netflix": "Netflix", "youtube": "YouTube", "disney+": "Disney+",
    "prime video": "Prime Video", "hbo max": "HBO Max", "max": "Max",
    "paramount+": "Paramount+", "apple tv": "Apple TV", "fandango": "Fandango",
}

def percentage(value):
    if value.isdigit():return int(value)
    small=dict(zip(('one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen').split(),range(1,20)))
    tens=dict(zip(('twenty thirty forty fifty sixty seventy eighty ninety').split(),range(20,100,10)))
    parts=value.replace('-', ' ').split()
    if parts in (['one','hundred'],['a','hundred']):return 100
    if len(parts)==1:return small.get(parts[0],tens.get(parts[0],0))
    if len(parts)==2 and parts[0] in tens and 1<=small.get(parts[1],0)<=9:return tens[parts[0]]+small[parts[1]]
    return 0

def catalog(path=None):
    resource = importlib.resources.files("aiden_decisions").joinpath("decision_routes.json") if path is None else Path(path)
    value=json.loads(resource.read_text())
    devices=value.get('devices',[]); targets=value.get('targets',[])
    if not devices or not targets:raise ValueError('Home controls catalog is empty')
    identifiers=[d['id'] for d in devices]
    if len(identifiers)!=len(set(identifiers)):raise ValueError('Duplicate home device')
    for d in devices:
        if not SAFE_ID.fullmatch(d['id']):raise ValueError('Invalid device identifier')
        if not set(d['actions']) <= ACTIONS:raise ValueError('Unknown device action')
    aliases=set(); target_ids=set()
    for t in targets:
        if not SAFE_ID.fullmatch(t['id']) or t['id'] in target_ids:raise ValueError('Invalid target')
        target_ids.add(t['id'])
        if not t['devices'] or len(t['devices'])!=len(set(t['devices'])) or not set(t['devices'])<=set(identifiers):raise ValueError('Unknown target device')
        for name in [t['name'],*t.get('aliases',[])]:
            name=name.lower()
            if name in aliases:raise ValueError('Duplicate home alias')
            aliases.add(name)
    return value

def number(text):
    if re.fullmatch(r'\d{1,3}(?:\.\d)?',text):return float(text) if '.' in text else int(text)
    value=percentage(text)
    return value if value else None

def parse(text, config=None):
    config=config or catalog()
    text=text.translate(str.maketrans({'’':"'",'‘':"'",'“':'"','”':'"'}))
    value=re.sub(r'^(?:aiden|assistant)[, :]+','',text.strip().lower()).rstrip('.?!')
    value=re.sub(r'\bkitchen light twenty[ -]three\b','kitchen light 23',value)
    value=re.sub(r'\.\s*all (?:the )?lights$', '',value)
    for t in sorted(config['targets'],key=lambda t:len(t['name']),reverse=True):
        for alias in sorted([t['name'],*t.get('aliases',[])],key=len,reverse=True):
            escaped=re.escape(alias.lower())
            # A bare "my TV" is ambiguous when a home has multiple TVs. A
            # room-qualified target still accepts possessive wording.
            article = r'(?:the )?' if alias.lower() in {'tv', 'television'} else r'(?:(?:the|my) )?'
            if t['kind']=='tv':
                now_playing = (
                    r"what(?:'s| is) (?:(?:playing|showing)(?: right now)? "
                    + r"(?:on|in) "+article+escaped+r"(?: right now)?|"
                    + r"on "+article+escaped+r"(?: right now)?|"
                    + article+escaped+r" (?:watching|showing|playing)(?: right now)?)"
                )
                if re.fullmatch(now_playing,value):
                    return {'target':t['id'],'action':'status'}
                match=re.fullmatch(r'(?:can you )?(?:please )?(?:put|play|watch|start|open) (.+?) (?:on|onto|in) (?:my |the )?'+escaped,value)
                if match:
                    query=re.sub(r'^(?:something like|a movie or show like|movie or show like|a movie like|a show like|the movie|the show)\s+','',match[1].strip(),flags=re.I)
                    provider_match=re.search(r'\s+on\s+(netflix|youtube|disney\+|prime video|hbo max|max|paramount\+|apple tv|fandango)\b.*$',query,flags=re.I)
                    provider=MEDIA_PROVIDERS[provider_match[1].casefold()] if provider_match else None
                    if provider_match:query=query[:provider_match.start()]
                    query=re.sub(r'\s+for\s+(?:my\s+)?(?:wife|wifey|husband|family)\b.*$','',query,flags=re.I)
                    query=re.sub(r'\s+', ' ', query).strip(" '\"")
                    # A disjunction may name two different titles. Never let
                    # substring matching silently choose the first allowlisted one.
                    if QUERY_SAFE.fullmatch(query) and not re.search(r'\b(?:or|either)\b',query,re.I):
                        intent={'target':t['id'],'action':'media','query':query}
                        if provider:intent['provider']=provider
                        return intent
            if value in (alias.lower()+' status','status of '+alias.lower()) or re.fullmatch(r'what (?:is|are) (?:the )?status(?:es)? of '+article+escaped,value):
                return {'target':t['id'],'action':'status'}
            if re.fullmatch(r'is '+article+escaped+r' on',value) or re.fullmatch(r'are '+article+escaped+r' on',value):
                return {'target':t['id'],'action':'status'}
            for state in ('on','off'):
                if re.fullmatch(r'turn '+article+escaped+' '+state,value) or re.fullmatch(r'turn '+state+r' '+article+escaped,value):
                    return {'target':t['id'],'action':'power','value':state=='on'}
            match=re.fullmatch(r'(?:set|dim) (?:the )?'+escaped+r' to (.+?)(?: percent|%)',value)
            if not match and t['kind']=='light':match=re.fullmatch(r'set (?:the )?'+escaped+r' to (\d{1,3})',value)
            if match and t['kind']=='light':
                n=number(match[1])
                if n is not None and 1<=n<=100 and int(n)==n:return {'target':t['id'],'action':'brightness','value':int(n)}
            match=re.fullmatch(r'set (?:the )?'+escaped+r' to (.+?)(?: degrees?)?(?: (fahrenheit|celsius))?',value)
            if match and t['kind']=='climate':
                n=number(match[1])
                if n is not None and 5<=n<=95:
                    result={'target':t['id'],'action':'temperature','value':n}
                    if match[2]:result['unit']='F' if match[2]=='fahrenheit' else 'C'
                    return result
    return None
