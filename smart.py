
import re, hashlib
from dataclasses import dataclass

@dataclass
class Detection:
    rule_code:str
    reason:str
    severity:int
    score:int

INSULTS = {
    "дебил","идиот","тупой","тупая","даун","урод","уродина","мразь","чмо",
    "долбоеб","долбаеб","еблан","мудак","уебок","уёбок","гнида","тварь",
    "шлюха","лох","кретин","петух","ничтожество","тупица"
}
STRONG_INSULTS = {
    "долбоеб","долбаеб","уебок","уёбок","мразь","шлюха","гнида"
}
PROVOCATIONS = {
    "закрой рот","заткнись","иди нахуй","пошел нахуй","пошёл нахуй",
    "свали отсюда","тебя никто не спрашивал","кто тебя спрашивал"
}
PAVLOVA_NEG = {
    "ненавижу","ужасная","страшная","мерзкая","дура","кринж","отстой",
    "фу","бесит","жалкая","позор"
}
ADVERTISEMENT_HINTS = {
    "подпишись","подписывайся","заходи в канал","мой канал","мой сервер",
    "услуги","продам","купить у меня","переходи"
}

URL_RE = re.compile(r"(https?://|t\.me/|discord\.gg/|www\.)", re.I)
MANY_CHARS_RE = re.compile(r"(.)\1{7,}", re.I)
ALL_CAPS_RE = re.compile(r"^[^a-zа-яё]*[A-ZА-ЯЁ][A-ZА-ЯЁ0-9 !?.,_-]{12,}$")

def normalize(text:str)->str:
    t=(text or "").lower().replace("ё","е")
    t=re.sub(r"[^\w@#:/.\s-]+"," ",t,flags=re.UNICODE)
    return re.sub(r"\s+"," ",t).strip()

def tokens(text:str):
    return set(re.findall(r"[\w@#]+",normalize(text),re.UNICODE))

def fingerprint(text:str)->str:
    n=normalize(text)
    return hashlib.sha1(n.encode("utf-8")).hexdigest()

def mentions_any(text:str,names:set[str])->bool:
    n=normalize(text)
    return any(name.lower() in n for name in names)

def aimed_at_bot(text:str,bot_names:set[str],reply_to_bot:bool)->bool:
    if reply_to_bot:
        return True
    n=normalize(text)
    return any(x in n for x in bot_names)

def analyze_text(text:str,bot_names:set[str],pavlova_names:set[str],reply_to_bot:bool=False):
    if not text:
        return None

    n=normalize(text)
    toks=tokens(text)

    # Special exemption: insults toward the bot itself are ignored.
    if aimed_at_bot(text,bot_names,reply_to_bot):
        return None

    score=0
    reasons=[]
    rule="RESPECT"
    severity=1

    insult_hits=sorted(toks & INSULTS)
    strong_hits=sorted(toks & STRONG_INSULTS)
    prov_hits=sorted(p for p in PROVOCATIONS if p in n)

    if insult_hits:
        score += 45 + min(20, len(insult_hits)*7)
        severity=max(severity,2)
        reasons.append("оскорбление")
    if strong_hits:
        score += 20
        severity=max(severity,3)
        reasons.append("жёсткое оскорбление")
    if prov_hits:
        score += 30
        severity=max(severity,2)
        reasons.append("провокация")

    # Pavlova rule is intentionally stricter.
    if mentions_any(text,pavlova_names):
        pav_bad=bool(toks & PAVLOVA_NEG) or bool(insult_hits) or bool(prov_hits)
        if pav_bad:
            return Detection("PAVLOVA","Негатив / оскорбление Павловой",3,100)

    if MANY_CHARS_RE.search(text):
        return Detection("SPAM","Флуд повторяющимися символами",1,80)

    if URL_RE.search(n) and any(h in n for h in ADVERTISEMENT_HINTS):
        return Detection("AD","Самовольная реклама / ссылка",2,90)

    if score >= 45:
        return Detection(rule," / ".join(dict.fromkeys(reasons)) or "токсичное сообщение",severity,min(score,100))

    return None

async def analyze_behavior(db,chat_id,user_id,text):
    fp=fingerprint(text)
    repeated=await db.repeated_count(chat_id,user_id,fp,seconds=60)
    rate=await db.message_rate(chat_id,user_id,seconds=20)

    if repeated >= 3:
        return Detection("SPAM","Повтор одного и того же сообщения",2,95)
    if rate >= 9:
        return Detection("SPAM","Слишком много сообщений за короткое время",2,90)
    return None
