import os
import re
import json
import hashlib
import urllib.request
import urllib.parse
import requests
import base64
from datetime import datetime
from flask import Flask, request, abort, jsonify
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage, ImageMessage,
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent, ImageMessageContent
)

app = Flask(__name__)
configuration = Configuration(access_token=os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))

THAI_PATTERN = re.compile(r"[\u0E00-\u0E7F]")
CHINESE_PATTERN = re.compile(r"[\u4E00-\u9FFF\u3400-\u4DBF]")

def mymemory_translate(text, src, dest):
    url = "https://api.mymemory.translated.net/get"
    params = urllib.parse.urlencode({"q": text[:500], "langpair": f"{src}|{dest}"})
    req = urllib.request.Request(f"{url}?{params}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    result = data.get("responseData", {}).get("translatedText", "")
    if not result:
        raise Exception("無翻譯結果")
    return result

def google_translate(text, src, dest):
    url = "https://translate.googleapis.com/translate_a/single"
    params = urllib.parse.urlencode({"client": "gtx", "sl": src, "tl": dest, "dt": "t", "q": text})
    req = urllib.request.Request(f"{url}?{params}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    return "".join([seg[0] for seg in data[0] if seg[0]])

def translate(text, src="auto", dest="zh-TW"):
    try:
        return mymemory_translate(text, src, dest)
    except Exception:
        return google_translate(text, src, dest)

def is_thai(text):
    return bool(THAI_PATTERN.search(text))

def is_chinese(text):
    return bool(CHINESE_PATTERN.search(text))

# ── 星座運勢 ──────────────────────────────────────────
ZODIAC_SIGNS = {
    "牡羊座": "aries", "金牛座": "taurus", "雙子座": "gemini",
    "巨蟹座": "cancer", "獅子座": "leo", "處女座": "virgo",
    "天秤座": "libra", "天蠍座": "scorpio", "射手座": "sagittarius",
    "摩羯座": "capricorn", "水瓶座": "aquarius", "雙魚座": "pisces",
    "白羊座": "aries", "人馬座": "sagittarius", "山羊座": "capricorn",
}

ZODIAC_DATA = {
    "aries": {
        "name": "牡羊座 ♈", "date": "3/21–4/19",
        "traits": ["衝勁十足", "勇敢果斷", "熱情積極", "獨立自主", "開朗率直"],
        "lucky_color": ["紅色", "橙色"],
        "lucky_num": ["1", "9"],
        "fortune": [
            "今日運勢旺盛，適合主動出擊，把握機會。感情方面有新的發展，單身者可能遇到心儀對象。",
            "工作上需謹慎，避免衝動決策。財運平平，不宜大額投資。感情穩定，與伴侶溝通順暢。",
            "今日貴人運強，多與人交流，可獲意外之喜。工作順利，有機會獲得上司賞識。",
            "精力充沛，適合處理積壓已久的事務。感情方面需多包容，避免爭執。",
            "創意思維活躍，工作上有新點子冒出。財運不錯，小投資可嘗試。",
        ]
    },
    "taurus": {
        "name": "金牛座 ♉", "date": "4/20–5/20",
        "traits": ["穩重踏實", "耐心持久", "重視物質", "品味獨到", "忠誠可靠"],
        "lucky_color": ["綠色", "粉色"],
        "lucky_num": ["2", "6"],
        "fortune": [
            "財運亨通，適合理財規劃。工作穩步推進，感情生活甜蜜，適合與伴侶約會。",
            "今日宜靜不宜動，避免衝動消費。感情方面需要多一些耐心，感情進展順利。",
            "工作運佳，努力會得到回報。財運平穩，可考慮長期投資。感情溫馨穩定。",
            "今日適合享受生活，美食、音樂、藝術都能帶來愉悅。財運小有進帳。",
            "事業有所突破，得到認可。感情需要主動表達，不要只等對方。",
        ]
    },
    "gemini": {
        "name": "雙子座 ♊", "date": "5/21–6/21",
        "traits": ["思維敏捷", "口才出眾", "好奇心強", "適應力強", "多才多藝"],
        "lucky_color": ["黃色", "天藍色"],
        "lucky_num": ["3", "7"],
        "fortune": [
            "溝通運極佳，今日適合談判、簽約。社交活躍，可能結識重要人脈。感情甜蜜。",
            "思緒紛雜，難以集中，做事容易分心。感情上可能有些小誤解需要澄清。",
            "靈感爆發，創意工作大放異彩。財運不錯，意外之財有機會降臨。",
            "今日人緣極佳，朋友相聚帶來好心情。感情方面輕鬆愉快，享受當下。",
            "工作上需要做出選擇，謹慎分析利弊。感情雙線進行，需理清思路。",
        ]
    },
    "cancer": {
        "name": "巨蟹座 ♋", "date": "6/22–7/22",
        "traits": ["情感豐富", "直覺敏銳", "居家顧家", "溫柔體貼", "記憶力強"],
        "lucky_color": ["銀色", "白色"],
        "lucky_num": ["2", "7"],
        "fortune": [
            "情緒敏感，容易受環境影響。家人帶來溫暖，感情上需多關心伴侶。",
            "直覺準確，重要決策可相信內心感受。財運有起伏，穩健為宜。",
            "今日適合照顧家人，家庭生活和諧美滿。工作上有同事支持，事半功倍。",
            "情感豐沛，適合創作或藝術活動。感情方面浪漫氛圍濃，與伴侶共度美好時光。",
            "財運需謹慎，避免不必要的支出。工作需要更多耐心，堅持就能看到成果。",
        ]
    },
    "leo": {
        "name": "獅子座 ♌", "date": "7/23–8/22",
        "traits": ["自信威嚴", "領導才能", "慷慨大方", "熱情活力", "追求完美"],
        "lucky_color": ["金色", "橙色"],
        "lucky_num": ["1", "5"],
        "fortune": [
            "今日光芒四射，是展現自我的好時機。工作上受到注目，感情方面魅力無限。",
            "創意與熱情兼具，適合推動新計畫。財運佳，可把握投資機會。",
            "領導力突出，帶領團隊達成目標。感情穩定甜蜜，被愛包圍的一天。",
            "今日稍需謹慎，避免過度自信造成失誤。感情上多傾聽伴侶的想法。",
            "人際關係活躍，貴人相助讓事情順利推進。財運不錯，有意外收入。",
        ]
    },
    "virgo": {
        "name": "處女座 ♍", "date": "8/23–9/22",
        "traits": ["細心謹慎", "分析力強", "追求完美", "勤奮努力", "服務精神"],
        "lucky_color": ["深綠色", "棕色"],
        "lucky_num": ["5", "8"],
        "fortune": [
            "分析能力出色，今日適合處理細節事務。財務規劃得宜，健康需多注意休息。",
            "完美主義發揮，工作品質卓越。感情方面需放鬆標準，多欣賞對方優點。",
            "工作效率高，得到上司認可。財運穩健，理財計畫順利執行。",
            "今日適合整理環境和思緒，清爽的環境帶來好心情。感情平穩溫馨。",
            "直覺敏銳，能察覺問題所在。感情上溝通順暢，雙方更加了解彼此。",
        ]
    },
    "libra": {
        "name": "天秤座 ♎", "date": "9/23–10/23",
        "traits": ["公平正義", "優雅品味", "社交達人", "追求和諧", "決策困難"],
        "lucky_color": ["粉色", "淺藍色"],
        "lucky_num": ["6", "9"],
        "fortune": [
            "人際關係和諧，今日適合社交與合作。感情甜蜜，伴侶關係更進一步。",
            "需要做出重要選擇，多方考量後果斷決定。財運平穩，維持現狀為佳。",
            "藝術品味發揮，適合欣賞美好事物。感情浪漫，享受二人世界。",
            "公平處事得到眾人信任，工作合作順利。財運有小進帳，可考慮小額投資。",
            "今日社交運旺，廣結善緣帶來好機會。感情方面可主動表達心意。",
        ]
    },
    "scorpio": {
        "name": "天蠍座 ♏", "date": "10/24–11/22",
        "traits": ["洞察力強", "意志堅定", "神秘魅力", "感情深刻", "變革能力"],
        "lucky_color": ["深紅色", "黑色"],
        "lucky_num": ["8", "9"],
        "fortune": [
            "洞察力超強，能看穿事情本質。感情深刻濃烈，與伴侶心靈相連。",
            "今日直覺準確，相信自己的判斷。財運不錯，隱藏的資源可能浮出水面。",
            "意志堅定，克服困難靠的就是這股韌勁。工作上有突破性進展。",
            "神秘魅力吸引他人，感情方面桃花旺盛。需謹慎選擇，避免感情糾紛。",
            "今日適合深度思考與規劃，為未來佈局。財運需要耐心等待，勿急躁。",
        ]
    },
    "sagittarius": {
        "name": "射手座 ♐", "date": "11/23–12/21",
        "traits": ["樂觀開朗", "愛好自由", "哲學思考", "冒險精神", "幽默風趣"],
        "lucky_color": ["紫色", "深藍色"],
        "lucky_num": ["3", "9"],
        "fortune": [
            "冒險精神旺盛，今日適合嘗試新事物。旅行或學習帶來驚喜，感情自由愉快。",
            "樂觀態度感染身邊的人，工作氣氛活躍。財運有意外之財，保持開放心態。",
            "哲學思考讓你看到更大的格局，工作決策英明。感情愉快，享受戀愛的自由。",
            "社交圈擴大，認識來自不同背景的朋友。感情上可能有異地緣分出現。",
            "今日充滿活力，適合戶外活動。財運穩健，踏實努力就能有所收穫。",
        ]
    },
    "capricorn": {
        "name": "摩羯座 ♑", "date": "12/22–1/19",
        "traits": ["踏實穩重", "責任感強", "目標明確", "耐力十足", "務實進取"],
        "lucky_color": ["深棕色", "黑色"],
        "lucky_num": ["4", "8"],
        "fortune": [
            "事業心旺盛，今日努力換來實質回報。財運穩健上升，理財規劃成效顯著。",
            "責任感讓你在工作中脫穎而出，獲得信賴。感情需要更多溫柔，放下嚴肅面。",
            "目標清晰，步步為營的策略奏效。財運不錯，長期投資看到成果。",
            "今日需要休息調整，不要過度工作。感情方面與伴侶共享輕鬆時光。",
            "貴人運佳，長輩或前輩給予重要指引。財運有提升，把握穩健機會。",
        ]
    },
    "aquarius": {
        "name": "水瓶座 ♒", "date": "1/20–2/18",
        "traits": ["獨立創新", "人道主義", "思維超前", "重視友情", "反傳統"],
        "lucky_color": ["藍色", "銀色"],
        "lucky_num": ["4", "7"],
        "fortune": [
            "創新思維帶來突破，工作上有革命性的新想法。感情自由愉快，尊重彼此空間。",
            "社群運旺，朋友帶來意想不到的機會。財運靠人際關係，廣結善緣。",
            "今日適合投入公益或團體活動，成就感滿滿。感情真誠交流，心靈契合。",
            "獨特見解得到認可，工作成就感高。財運需要創新方式，傳統方法效果有限。",
            "思維超前，但需腳踏實地執行。感情需要更多承諾，讓對方有安全感。",
        ]
    },
    "pisces": {
        "name": "雙魚座 ♓", "date": "2/19–3/20",
        "traits": ["感情豐富", "藝術天賦", "直覺敏銳", "善解人意", "夢想主義"],
        "lucky_color": ["海藍色", "紫色"],
        "lucky_num": ["7", "11"],
        "fortune": [
            "直覺超準，今日相信第六感做決定。藝術創作靈感豐沛，感情浪漫如詩。",
            "夢想與現實需要平衡，腳踏實地才能實現理想。財運依靠直覺，有意外收穫。",
            "善解人意的特質讓你成為貴人，幫助他人也帶來福氣。感情溫柔細膩。",
            "今日適合靜思冥想，靈感在寧靜中湧現。感情方面靈魂連結，深刻動人。",
            "創意工作大放異彩，才華得到欣賞。財運靠直覺，謹慎判斷後行動。",
        ]
    },
}

# ── 財運運勢 ──────────────────────────────────────────
WEALTH_FORTUNE = [
    {
        "level": "💰💰💰💰💰 財運大旺",
        "desc": "今日財星高照，是投資理財的絕佳時機！主動出擊，不論是股票、基金或小生意，都有機會獲利。意外之財也可能從意想不到的地方降臨，保持開放心態。",
        "tips": ["適合簽約、談合同", "可小額投資試水溫", "貴人帶來財富機遇"],
        "avoid": "避免大額賭博性投機"
    },
    {
        "level": "💰💰💰💰 財運頗佳",
        "desc": "財運良好，工作上的努力開始看到回報。薪資、獎金或業績獎勵有望到來。適合整理財務，規劃未來的理財目標。",
        "tips": ["穩健投資可進行", "適合整理帳目", "收入有望增加"],
        "avoid": "避免衝動消費名牌或奢侈品"
    },
    {
        "level": "💰💰💰 財運平穩",
        "desc": "今日財運中規中矩，收支平衡。適合守成，不宜冒險。日常開銷正常，但要注意控制不必要的花費，為未來儲蓄。",
        "tips": ["維持現有財務計畫", "節省日常開銷", "適合記帳理財"],
        "avoid": "避免借貸給他人"
    },
    {
        "level": "💰💰 財運略低",
        "desc": "今日財運稍弱，可能有意外支出或花費超出預算。需特別注意錢包、手機等財物，避免遺失。投資決策宜謹慎，多觀察少出手。",
        "tips": ["謹慎保管財物", "暫停非必要投資", "避免大額消費"],
        "avoid": "避免借錢給朋友或借錢度日"
    },
    {
        "level": "💰 財運需謹慎",
        "desc": "今日財運較弱，破財風險較高。切勿進行投機性投資，也要小心詐騙或不實商機。保守理財，守住現有資產才是上策。",
        "tips": ["低調行事，守住財富", "不輕信投資話術", "今日不宜大額交易"],
        "avoid": "完全避免任何形式的賭博或投機"
    },
]

def get_zodiac_fortune(zodiac_key, user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    seed = hashlib.md5(f"{user_id}{today}{zodiac_key}".encode()).hexdigest()
    fortune_idx = int(seed[:8], 16) % 5
    lucky_idx = int(seed[8:16], 16) % len(ZODIAC_DATA[zodiac_key]["traits"])
    
    data = ZODIAC_DATA[zodiac_key]
    fortune = data["fortune"][fortune_idx]
    stars = ["⭐", "⭐⭐", "⭐⭐⭐", "⭐⭐⭐⭐", "⭐⭐⭐⭐⭐"][fortune_idx]
    
    return (
        f"✨ {data['name']} 今日運勢\n"
        f"({data['date']})\n"
        f"{'─'*18}\n"
        f"綜合運勢：{stars}\n\n"
        f"{fortune}\n\n"
        f"🍀 今日幸運色：{'、'.join(data['lucky_color'])}\n"
        f"🔢 幸運數字：{'、'.join(data['lucky_num'])}\n"
        f"✨ 今日關鍵字：{data['traits'][lucky_idx]}\n"
        f"{'─'*18}\n"
        f"傳「財運」查看今日財運"
    )

def get_wealth_fortune(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    seed = hashlib.md5(f"{user_id}{today}wealth".encode()).hexdigest()
    idx = int(seed[:8], 16) % len(WEALTH_FORTUNE)
    w = WEALTH_FORTUNE[idx]
    tips_str = "\n".join([f"✅ {t}" for t in w["tips"]])
    return (
        f"💵 {datetime.now().strftime('%Y年%m月%d日')} 財運預測\n"
        f"{'─'*18}\n"
        f"{w['level']}\n\n"
        f"{w['desc']}\n\n"
        f"今日財運建議：\n{tips_str}\n\n"
        f"⚠️ {w['avoid']}\n"
        f"{'─'*18}\n"
        f"傳「星座」查看星座運勢 ✨"
    )

# ── BTS 站點資料 ──────────────────────────────────────
BTS_STATIONS = {
    "หมอชิต": ("หมอชิต/Mo Chit", [
        ("จตุจักร มาร์เก็ต｜札都甲市場", "曼谷最大週末市集，超過1萬個攤位，週六日開放"),
        ("สวนจตุจักร｜札都甲公園", "廣大的都市公園，適合散步休閒"),
    ]),
    "อารีย์": ("อารีย์/Ari", [
        ("ย่านอารีย์｜Ari 文青區", "咖啡廳、藝廊、餐廳林立，曼谷最潮文青聚集地"),
    ]),
    "สยาม": ("สยาม/Siam", [
        ("สยามพารากอน｜暹羅百麗宮", "頂級購物中心，奢侈品牌、美食、水族館"),
        ("สยามเซ็นเตอร์｜暹羅中心", "年輕時尚品牌聚集"),
        ("MBK Center｜馬布空購物中心", "手機3C、平價商品，殺價天堂"),
    ]),
    "ชิดลม": ("ชิดลม/Chit Lom", [
        ("เซ็นทรัลเวิลด์｜中央世界", "東南亞最大購物中心之一"),
        ("สวนลุมพินี｜倫披尼公園", "曼谷最大城市公園"),
    ]),
    "อโศก": ("อโศก/Asok", [
        ("เทอมินัล21｜Terminal 21", "世界機場主題購物中心，每層樓是不同城市"),
    ]),
    "พร้อมพงษ์": ("พร้อมพงษ์/Phrom Phong", [
        ("เอ็มโพเรียม｜The Emporium", "高端購物中心，日系品牌齊全"),
        ("เอ็มควอเทียร์｜EmQuartier", "時尚購物中心，空中花園必拍"),
    ]),
    "ทองหล่อ": ("ทองหล่อ/Thong Lo", [
        ("ย่านทองหล่อ｜通羅時尚區", "曼谷最潮酒吧餐廳區"),
        ("J Avenue｜J大道", "文青商場，咖啡廳網紅打卡點"),
    ]),
    "อ่อนนุช": ("อ่อนนุช/On Nut", [
        ("ตลาดอ่อนนุช｜安努市場", "大型傳統市場，生活用品超齊全"),
    ]),
    "ราชดำริ": ("ราชดำริ/Ratchadamri", [
        ("ศาลพระพรหมเอราวัณ｜四面佛", "曼谷最靈驗的四面佛，香火鼎盛必拜"),
    ]),
    "ศาลาแดง": ("ศาลาแดง/Sala Daeng", [
        ("ถนนสีลม｜是隆路", "曼谷金融中心，頂級餐廳林立"),
        ("Patpong Night Market｜帕蓬夜市", "曼谷著名夜市"),
    ]),
    "สะพานตากสิน": ("สะพานตากสิน/Saphan Taksin", [
        ("เจ้าพระยา｜昭披耶河遊船", "搭船遊覽曼谷河景"),
        ("ไอคอนสยาม｜ICONSIAM", "超奢華河畔購物中心"),
    ]),
}

STATION_ALIASES = {
    "mo chit": "หมอชิต", "摩奇": "หมอชิต",
    "ari": "อารีย์", "阿里": "อารีย์",
    "siam": "สยาม", "暹羅": "สยาม",
    "chit lom": "ชิดลม", "奇隆": "ชิดลม",
    "asok": "อโศก", "阿速": "อโศก",
    "phrom phong": "พร้อมพงษ์", "澎蓬": "พร้อมพงษ์",
    "thong lo": "ทองหล่อ", "通羅": "ทองหล่อ",
    "on nut": "อ่อนนุช", "安努": "อ่อนนุช",
    "sala daeng": "ศาลาแดง", "是隆": "ศาลาแดง",
    "saphan taksin": "สะพานตากสิน", "達信橋": "สะพานตากสิน",
    "ratchadamri": "ราชดำริ", "四面佛站": "ราชดำริ",
}

def find_station(text):
    text_lower = text.lower().strip()
    for alias, thai in STATION_ALIASES.items():
        if alias in text_lower or alias in text:
            return thai
    for thai in BTS_STATIONS:
        if thai in text:
            return thai
    return None

def get_station_info(station_key):
    name, spots = BTS_STATIONS[station_key]
    lines = [f"🚈 BTS {name}", "─" * 18, "📍 附近景點推薦："]
    for i, (spot, desc) in enumerate(spots, 1):
        lines.append(f"\n{i}. {spot}")
        lines.append(f"   {desc}")
    lines.append("\n─" * 18)
    lines.append("傳「抽卦」可得今日卦象 ☯")
    return "\n".join(lines)

# ── 六十四卦 ──────────────────────────────────────────
HEXAGRAMS = [
    ("乾","天","剛健中正，自強不息。\n運勢：諸事順遂，宜積極進取。\n提醒：切忌過於剛強，物極必反。"),
    ("坤","地","厚德載物，順勢而為。\n運勢：萬事宜穩健，靜待時機。\n提醒：柔順謙遜，方得長久。"),
    ("屯","水雷","初生之難，萬物始生。\n運勢：困難重重，但前途光明。\n提醒：堅持不懈，終有所成。"),
    ("蒙","山水","啟蒙求知，虛心學習。\n運勢：宜多請益，勿剛愎自用。\n提醒：謙遜求教，智慧自來。"),
    ("需","水天","等待時機，靜養蓄銳。\n運勢：當前宜靜不宜動。\n提醒：機會將至，養精蓄銳。"),
    ("訟","天水","爭訟是非，戒之慎之。\n運勢：易生口舌之爭，退讓為佳。\n提醒：和為貴，息爭止訟。"),
    ("師","地水","統帥之道，以德服眾。\n運勢：宜團結眾人，以正道行事。\n提醒：領導需以德，眾志成城。"),
    ("比","水地","親比相輔，互助合作。\n運勢：貴人相助，合作共贏。\n提醒：廣結善緣，互惠互利。"),
    ("小畜","風天","小有積蓄，蓄勢待發。\n運勢：小事可成，大事需等待。\n提醒：積少成多，循序漸進。"),
    ("履","天澤","謹慎行事，步步為營。\n運勢：謹慎即可化解風險。\n提醒：如履薄冰，謹言慎行。"),
    ("泰","地天","天地交泰，萬物繁榮。\n運勢：大吉大利，諸事亨通。\n提醒：順境中仍需居安思危。"),
    ("否","天地","天地不交，萬物不通。\n運勢：諸事不順，宜守不宜攻。\n提醒：逆境終將過去，靜待轉機。"),
    ("同人","天火","與人同心，協力共事。\n運勢：人際關係佳，合作有成。\n提醒：以誠待人，廣結善緣。"),
    ("大有","火天","大有所獲，豐收之象。\n運勢：財運亨通，事業有成。\n提醒：富貴不忘本，謙遜待人。"),
    ("謙","地山","謙遜自牧，德行兼備。\n運勢：謙遜行事，貴人自來。\n提醒：滿招損，謙受益。"),
    ("豫","雷地","歡欣鼓舞，預備充足。\n運勢：心情愉快，事事如意。\n提醒：樂極生悲，適可而止。"),
    ("隨","澤雷","順時而動，隨機應變。\n運勢：順勢而為，機遇自來。\n提醒：不可隨波逐流，需有主見。"),
    ("蠱","山風","革故鼎新，整頓局面。\n運勢：宜改革創新。\n提醒：積弊需革除，方能煥然一新。"),
    ("臨","地澤","臨事慎重，親自督導。\n運勢：凡事宜親力親為。\n提醒：親臨其事，方得其實。"),
    ("觀","風地","觀察形勢，知己知彼。\n運勢：宜多觀察，靜待時機。\n提醒：知彼知己，百戰不殆。"),
    ("噬嗑","火雷","咬破障礙，果斷決策。\n運勢：宜果斷行事，突破困境。\n提醒：當機立斷，勿優柔寡斷。"),
    ("賁","山火","文飾外表，注重形象。\n運勢：外表光鮮，需注重內涵。\n提醒：華而不實，終非長久。"),
    ("剝","山地","剝落衰退，去舊迎新。\n運勢：此時宜守不宜進。\n提醒：剝極而復，否極泰來。"),
    ("復","地雷","回復正道，重振旗鼓。\n運勢：低潮已過，好運將至。\n提醒：回頭是岸，重新出發。"),
    ("無妄","天雷","無妄之災，順天而行。\n運勢：凡事不可強求，順其自然。\n提醒：行正道，避橫禍。"),
    ("大畜","山天","大量積蓄，厚積薄發。\n運勢：積累已足，可大展宏圖。\n提醒：時機成熟則行。"),
    ("頤","山雷","頤養正道，滋養身心。\n運勢：宜注重健康飲食。\n提醒：禍從口出，病從口入。"),
    ("大過","澤風","大有過失，力挽狂瀾。\n運勢：處境艱難，需奮力一搏。\n提醒：非常時期，需非常手段。"),
    ("坎","水","重重險阻，百折不撓。\n運勢：困難重重，堅持必能渡過。\n提醒：臨危不亂，沉著應對。"),
    ("離","火","光明磊落，文明昌盛。\n運勢：前途光明，才華得以發揮。\n提醒：光而不耀，謙遜為懷。"),
    ("咸","澤山","感應相通，男女相交。\n運勢：感情順遂，人際和諧。\n提醒：以誠相感，心靈相通。"),
    ("恆","雷風","持之以恆，永恆不變。\n運勢：堅持到底，必有所成。\n提醒：恆心是成功之母。"),
    ("遯","天山","隱退避世，以退為進。\n運勢：宜暫退一步，待機而動。\n提醒：退一步海闊天空。"),
    ("大壯","雷天","大而且壯，剛健有力。\n運勢：運勢旺盛，宜積極行動。\n提醒：壯而知止，方為大壯。"),
    ("晉","火地","晉升前進，光明在前。\n運勢：升遷有望，前途光明。\n提醒：穩步前進，勿躁進。"),
    ("明夷","地火","光明受損，韜光養晦。\n運勢：暫時受挫，宜低調行事。\n提醒：韜光養晦，等待時機。"),
    ("家人","風火","家庭和睦，各司其職。\n運勢：家庭和諧，事業順遂。\n提醒：家和萬事興。"),
    ("睽","火澤","乖違不合，分歧對立。\n運勢：易生誤解，溝通需努力。\n提醒：求同存異，化解對立。"),
    ("蹇","水山","步履維艱，艱難前行。\n運勢：諸事不順，宜尋求外援。\n提醒：知難而退，另謀出路。"),
    ("解","雷水","解除困難，撥雲見日。\n運勢：困境解除，好運降臨。\n提醒：寬恕他人，廣結善緣。"),
    ("損","山澤","損下益上，節制自律。\n運勢：宜節制開支，量入為出。\n提醒：損之又損，以至無為。"),
    ("益","風雷","增益補充，利人利己。\n運勢：諸事增益，財運亨通。\n提醒：取之有道，用之有節。"),
    ("夬","澤天","決斷去除，果斷行動。\n運勢：宜果斷決策，排除障礙。\n提醒：當斷則斷，勿留後患。"),
    ("姤","天風","邂逅相遇，機緣巧合。\n運勢：貴人相遇，機緣難得。\n提醒：把握緣分，珍惜相遇。"),
    ("萃","澤地","聚集匯萃，眾志成城。\n運勢：人氣旺盛，合作有成。\n提醒：團結力量大。"),
    ("升","地風","步步高升，循序漸進。\n運勢：事業上升，前途看好。\n提醒：一步一腳印，穩健上升。"),
    ("困","澤水","困頓之時，窮則思變。\n運勢：處境困難，需積極突破。\n提醒：絕處逢生。"),
    ("井","水風","井養萬民，取之不盡。\n運勢：資源充足，宜與人分享。\n提醒：飲水思源，回饋社會。"),
    ("革","澤火","革故鼎新，改革創新。\n運勢：改革時機已到，勇於創新。\n提醒：革命需順天應人。"),
    ("鼎","火風","鼎新革故，烹調萬物。\n運勢：事業鼎盛，創新有成。\n提醒：以新換舊，與時俱進。"),
    ("震","雷","震動驚懼，奮發圖強。\n運勢：受到震撼，能化危為機。\n提醒：臨危不懼，化險為夷。"),
    ("艮","山","止而不進，靜思內省。\n運勢：宜靜不宜動，深思熟慮。\n提醒：適時而止，方為明智。"),
    ("漸","風山","循序漸進，按部就班。\n運勢：事業漸入佳境，穩中求進。\n提醒：欲速則不達。"),
    ("歸妹","雷澤","嫁娶歸宿，終有所歸。\n運勢：感情有歸宿，但需謹慎。\n提醒：慎擇良緣，勿草率行事。"),
    ("豐","雷火","豐盛充實，盛極而衰。\n運勢：當前運勢旺盛，把握機會。\n提醒：盛極必衰，居安思危。"),
    ("旅","火山","旅途奔波，客居異鄉。\n運勢：適合旅行出差，外出有利。\n提醒：在外謹慎，廣結善緣。"),
    ("巽","風","順風而行，柔順謙遜。\n運勢：順風順水，凡事順遂。\n提醒：過於柔順則失去主見。"),
    ("兌","澤","喜悅和樂，口才出眾。\n運勢：人際關係佳，口才助事業。\n提醒：悅人悅己，和氣生財。"),
    ("渙","風水","渙散離析，聚散無常。\n運勢：凡事易散，需加強凝聚力。\n提醒：散而後聚，整合資源。"),
    ("節","水澤","節制有度，適可而止。\n運勢：宜節制，不可過度放縱。\n提醒：節儉自律，方能長久。"),
    ("中孚","風澤","誠信為本，以誠感人。\n運勢：誠信行事，必得人心。\n提醒：一諾千金，誠信是金。"),
    ("小過","雷山","小有過失，謹小慎微。\n運勢：小事易成，大事宜謹慎。\n提醒：謹慎小心，勿犯小過。"),
    ("既濟","水火","已經成功，圓滿完成。\n運勢：諸事圓滿，防樂極生悲。\n提醒：成功後仍需謹慎。"),
    ("未濟","火水","尚未完成，繼續努力。\n運勢：事業尚未完成，需繼續努力。\n提醒：堅持到底。"),
]

def get_daily_hexagram(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    seed = hashlib.md5(f"{user_id}{today}".encode()).hexdigest()
    idx = int(seed[:8], 16) % 64
    return HEXAGRAMS[idx]

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        reply_text = "🖼 圖片翻譯功能維護中，請直接輸入文字翻譯。\n\n傳中文→泰文，傳泰文→中文 🙂"
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip()
    user_id = event.source.user_id
    if not user_text:
        return

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # BTS 路線圖
        if user_text in ["路線圖", "BTS路線圖", "bts路線圖", "地圖", "map", "Map"]:
            bts_map_url = "https://www.bts.co.th/eng/img/bts-route-map.jpg"
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        ImageMessage(original_content_url=bts_map_url, preview_image_url=bts_map_url),
                        TextMessage(text="🚈 BTS 路線圖\n─────────────────\n🟢 Sukhumvit Line（綠線）\nMo Chit ↔ Bearing\n\n🟢 Silom Line（深綠線）\nNational Stadium ↔ Bang Wa\n\n傳「BTS 站名」查詢附近景點"),
                    ],
                )
            )
            return

        # 星座運勢選單
        if user_text in ["星座", "星座運勢", "今日星座"]:
            reply_text = (
                "✨ 請輸入你的星座：\n\n"
                "♈ 牡羊座（3/21–4/19）\n"
                "♉ 金牛座（4/20–5/20）\n"
                "♊ 雙子座（5/21–6/21）\n"
                "♋ 巨蟹座（6/22–7/22）\n"
                "♌ 獅子座（7/23–8/22）\n"
                "♍ 處女座（8/23–9/22）\n"
                "♎ 天秤座（9/23–10/23）\n"
                "♏ 天蠍座（10/24–11/22）\n"
                "♐ 射手座（11/23–12/21）\n"
                "♑ 摩羯座（12/22–1/19）\n"
                "♒ 水瓶座（1/20–2/18）\n"
                "♓ 雙魚座（2/19–3/20）\n\n"
                "直接傳星座名稱即可！"
            )

        # 星座查詢
        elif user_text in ZODIAC_SIGNS or any(z in user_text for z in ZODIAC_SIGNS):
            zodiac_key = ZODIAC_SIGNS.get(user_text)
            if not zodiac_key:
                for z, k in ZODIAC_SIGNS.items():
                    if z in user_text:
                        zodiac_key = k
                        break
            if zodiac_key:
                reply_text = get_zodiac_fortune(zodiac_key, user_id)
            else:
                reply_text = "請輸入正確的星座名稱，例如：牡羊座、金牛座"

        # 財運運勢
        elif user_text in ["財運", "今日財運", "財運運勢", "錢財", "投資運"]:
            reply_text = get_wealth_fortune(user_id)

        # 抽卦
        elif user_text in ["抽卦", "抽籤", "運勢", "今日運勢", "卦象"]:
            name, nature, desc = get_daily_hexagram(user_id)
            today = datetime.now().strftime("%Y年%m月%d日")
            reply_text = f"☯ {today} 今日卦象\n{'─'*18}\n【{name}卦】{nature}\n\n{desc}\n{'─'*18}\n每日一卦，明日再抽"

        # BTS 站點查詢
        elif "BTS" in user_text.upper() or "bts" in user_text.lower() or "站" in user_text:
            station_key = find_station(user_text)
            if station_key:
                reply_text = get_station_info(station_key)
            else:
                reply_text = "🚈 請輸入 BTS 站名查詢附近景點\n\n例如：\n「BTS Siam」「暹羅站」\n「BTS Asok」「阿速站」\n「BTS Thong Lo」「通羅站」"

        # 翻譯
        else:
            try:
                if is_thai(user_text):
                    translated = translate(user_text, "th", "zh-TW")
                    reply_text = f"🇹🇭 → 🇹🇼\n{translated}"
                elif is_chinese(user_text):
                    translated = translate(user_text, "zh-TW", "th")
                    reply_text = f"🇹🇼 → 🇹🇭\n{translated}"
                else:
                    reply_text = (
                        "📋 功能選單：\n"
                        "🔤 傳中文 → 翻譯成泰文\n"
                        "🔤 傳泰文 → 翻譯成中文\n"
                        "✨ 傳「星座」→ 選星座看運勢\n"
                        "💰 傳「財運」→ 今日財運預測\n"
                        "🚈 傳「BTS 站名」→ 附近景點\n"
                        "🗺 傳「路線圖」→ BTS 路線圖\n"
                        "☯ 傳「抽卦」→ 今日卦象"
                    )
            except Exception:
                reply_text = "⚠️ 翻譯失敗，請稍後再試。"

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
PYEOF
echo "Done"
