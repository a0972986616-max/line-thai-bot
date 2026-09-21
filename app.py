import os
import re
import json
import hashlib
import urllib.request
import urllib.parse
import requests
from datetime import datetime
from io import BytesIO
from PIL import Image
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

# ── 翻譯函式 ──────────────────────────────────────────
def mymemory_translate(text, src, dest):
    url = "https://api.mymemory.translated.net/get"
    params = urllib.parse.urlencode({"q": text, "langpair": f"{src}|{dest}"})
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

# ── 圖片 OCR 翻譯（使用 OCR.space 免費 API）──────────
def ocr_and_translate(image_data):
    # 使用 OCR.space 免費 API（支援泰文、英文）
    api_url = "https://api.ocr.space/parse/image"
    payload = {
        "apikey": "helloworld",  # 免費公開金鑰
        "language": "tha",       # 泰文優先
        "isOverlayRequired": False,
        "detectOrientation": True,
        "scale": True,
        "OCREngine": 2,
    }
    files = {"file": ("image.jpg", image_data, "image/jpeg")}
    resp = requests.post(api_url, data=payload, files=files, timeout=30)
    result = resp.json()

    if result.get("IsErroredOnProcessing"):
        # 改用英文模式重試
        payload["language"] = "eng"
        files = {"file": ("image.jpg", image_data, "image/jpeg")}
        resp = requests.post(api_url, data=payload, files=files, timeout=30)
        result = resp.json()

    parsed = result.get("ParsedResults", [])
    if not parsed:
        return None, None

    text = parsed[0].get("ParsedText", "").strip()
    if not text:
        return None, None

    # 偵測語言並翻譯
    if is_thai(text):
        translated = translate(text, "th", "zh-TW")
        lang = "泰文"
    else:
        translated = translate(text, "en", "zh-TW")
        lang = "英文"

    return text, translated, lang

# ── BTS 站點資料 ──────────────────────────────────────
BTS_STATIONS = {
    "หมอชิต": ("หมอชิต/Mo Chit", [
        ("จตุจักร มาร์เก็ต｜札都甲市場", "曼谷最大週末市集，超過1萬個攤位，週六日開放"),
        ("สวนจตุจักร｜札都甲公園", "廣大的都市公園，適合散步休閒"),
    ]),
    "อารีย์": ("อารีย์/Ari", [
        ("ย่านอารีย์｜Ari 文青區", "咖啡廳、藝廊、餐廳林立，曼谷最潮文青聚集地"),
        ("คาเฟ่อารีย์｜特色咖啡廳", "多家網紅打卡咖啡廳聚集"),
    ]),
    "สยาม": ("สยาม/Siam", [
        ("สยามพารากอน｜暹羅百麗宮", "頂級購物中心，奢侈品牌、美食、水族館"),
        ("สยามเซ็นเตอร์｜暹羅中心", "年輕時尚品牌聚集，設計感十足"),
        ("MBK Center｜馬布空購物中心", "手機3C、平價商品，殺價天堂"),
        ("หอศิลป์กรุงเทพ｜曼谷藝術文化中心", "免費當代藝術展覽"),
    ]),
    "ชิดลม": ("ชิดลม/Chit Lom", [
        ("เซ็นทรัลเวิลด์｜中央世界", "東南亞最大購物中心之一"),
        ("สวนลุมพินี｜倫披尼公園", "曼谷最大城市公園，晨跑、划船皆宜"),
    ]),
    "เพลินจิต": ("เพลินจิต/Phloen Chit", [
        ("เซ็นทรัล เอ็มบาสซี่｜中央大使館", "頂級購物中心，美食樓層超精彩"),
    ]),
    "นานา": ("นานา/Nana", [
        ("ถนนสุขุมวิท｜素坤逸路", "曼谷最國際化的大街，各國料理齊聚"),
    ]),
    "อโศก": ("อโศก/Asok", [
        ("เทอมินัล21｜Terminal 21", "世界機場主題購物中心，每層樓是不同城市"),
        ("สุขุมวิท ซอย 11｜素坤逸11巷", "酒吧餐廳林立，夜生活豐富"),
    ]),
    "พร้อมพงษ์": ("พร้อมพงษ์/Phrom Phong", [
        ("เอ็มโพเรียม｜The Emporium", "高端購物中心，日系品牌齊全"),
        ("เอ็มควอเทียร์｜EmQuartier", "時尚購物中心，空中花園必拍"),
    ]),
    "ทองหล่อ": ("ทองหล่อ/Thong Lo", [
        ("ย่านทองหล่อ｜通羅時尚區", "曼谷最潮酒吧餐廳區"),
        ("J Avenue｜J大道", "文青商場，咖啡廳網紅打卡點"),
    ]),
    "เอกมัย": ("เอกมัย/Ekkamai", [
        ("Gateway Ekamai｜Gateway 商場", "日系主題商場"),
        ("สถานีขนส่งเอกมัย｜東部巴士站", "前往芭達雅的巴士起點"),
    ]),
    "อ่อนนุช": ("อ่อนนุช/On Nut", [
        ("ตลาดอ่อนนุช｜安努市場", "大型傳統市場，生活用品超齊全"),
        ("Tesco Lotus On Nut｜Tesco蓮花", "大型超市，採購泰國伴手禮好去處"),
    ]),
    "ราชดำริ": ("ราชดำริ/Ratchadamri", [
        ("ศาลพระพรหมเอราวัณ｜四面佛", "曼谷最靈驗的四面佛，香火鼎盛必拜"),
        ("เซ็นทรัลเวิลด์｜中央世界", "步行可達東南亞最大購物中心"),
    ]),
    "ศาลาแดง": ("ศาลาแดง/Sala Daeng", [
        ("ถนนสีลม｜是隆路", "曼谷金融中心，頂級餐廳林立"),
        ("ลุมพินีพาร์ค｜倫披尼公園", "城市綠洲，有蜥蜴出沒超特別"),
        ("Patpong Night Market｜帕蓬夜市", "曼谷著名夜市"),
    ]),
    "สะพานตากสิน": ("สะพานตากสิน/Saphan Taksin", [
        ("เจ้าพระยา｜昭披耶河遊船", "搭船遊覽曼谷河景，欣賞寺廟與古建築"),
        ("ไอคอนสยาม｜ICONSIAM", "超奢華河畔購物中心，室內水上市場"),
    ]),
    "ช่องนนทรี": ("ช่องนนทรี/Chong Nonsi", [
        ("Sky Bar｜天空酒吧", "電影《醉後大丈夫》取景地，景色絕美"),
    ]),
    "วิคตอรี่มอนูเมนต์": ("วิคตอรี่มอนูเมนต์/Victory Monument", [
        ("อนุสาวรีย์ชัยสมรภูมิ｜勝利紀念碑", "泰國重要歷史地標，周邊小吃攤超多"),
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
    "ekkamai": "เอกมัย", "伊卡邁": "เอกมัย",
    "on nut": "อ่อนนุช", "安努": "อ่อนนุช",
    "sala daeng": "ศาลาแดง", "是隆": "ศาลาแดง",
    "saphan taksin": "สะพานตากสิน", "達信橋": "สะพานตากสิน",
    "ratchadamri": "ราชดำริ", "四面佛站": "ราชดำริ",
    "victory monument": "วิคตอรี่มอนูเมนต์", "勝利紀念碑": "วิคตอรี่มอนูเมนต์",
    "nana": "นานา", "那那": "นานา",
    "phloen chit": "เพลินจิต", "澎吉": "เพลินจิต",
    "chong nonsi": "ช่องนนทรี",
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
    if station_key not in BTS_STATIONS:
        return None
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
    ("乾","天","剛健中正，自強不息。\n運勢：諸事順遂，宜積極進取，把握良機。\n提醒：切忌過於剛強，物極必反。"),
    ("坤","地","厚德載物，順勢而為。\n運勢：萬事宜穩健，靜待時機，不宜冒進。\n提醒：柔順謙遜，方得長久。"),
    ("屯","水雷","初生之難，萬物始生。\n運勢：事業初創，困難重重，但前途光明。\n提醒：堅持不懈，終有所成。"),
    ("蒙","山水","啟蒙求知，虛心學習。\n運勢：宜多請益，勿剛愎自用。\n提醒：謙遜求教，智慧自來。"),
    ("需","水天","等待時機，靜養蓄銳。\n運勢：當前宜靜不宜動，耐心等待。\n提醒：機會將至，養精蓄銳。"),
    ("訟","天水","爭訟是非，戒之慎之。\n運勢：易生口舌之爭，凡事退讓為佳。\n提醒：和為貴，息爭止訟。"),
    ("師","地水","統帥之道，以德服眾。\n運勢：宜團結眾人，以正道行事。\n提醒：領導需以德，方能眾志成城。"),
    ("比","水地","親比相輔，互助合作。\n運勢：貴人相助，合作共贏。\n提醒：廣結善緣，互惠互利。"),
    ("小畜","風天","小有積蓄，蓄勢待發。\n運勢：小事可成，大事需再等待。\n提醒：積少成多，循序漸進。"),
    ("履","天澤","謹慎行事，步步為營。\n運勢：雖有風險，但只要謹慎即可化解。\n提醒：如履薄冰，謹言慎行。"),
    ("泰","地天","天地交泰，萬物繁榮。\n運勢：大吉大利，諸事亨通。\n提醒：順境中仍需居安思危。"),
    ("否","天地","天地不交，萬物不通。\n運勢：諸事不順，宜守不宜攻。\n提醒：逆境終將過去，靜待轉機。"),
    ("同人","天火","與人同心，協力共事。\n運勢：人際關係佳，合作事業有成。\n提醒：以誠待人，廣結善緣。"),
    ("大有","火天","大有所獲，豐收之象。\n運勢：財運亨通，事業有成。\n提醒：富貴不忘本，謙遜待人。"),
    ("謙","地山","謙遜自牧，德行兼備。\n運勢：謙遜行事，貴人自來。\n提醒：滿招損，謙受益。"),
    ("豫","雷地","歡欣鼓舞，預備充足。\n運勢：心情愉快，事事如意。\n提醒：樂極生悲，凡事適可而止。"),
    ("隨","澤雷","順時而動，隨機應變。\n運勢：順勢而為，機遇自來。\n提醒：不可隨波逐流，需有主見。"),
    ("蠱","山風","革故鼎新，整頓局面。\n運勢：宜改革創新，整頓事務。\n提醒：積弊需革除，方能煥然一新。"),
    ("臨","地澤","臨事慎重，親自督導。\n運勢：凡事宜親力親為。\n提醒：親臨其事，方得其實。"),
    ("觀","風地","觀察形勢，知己知彼。\n運勢：宜多觀察，靜待時機。\n提醒：知彼知己，百戰不殆。"),
    ("噬嗑","火雷","咬破障礙，果斷決策。\n運勢：宜果斷行事，突破困境。\n提醒：當機立斷，勿優柔寡斷。"),
    ("賁","山火","文飾外表，注重形象。\n運勢：外表光鮮，但需注重內涵。\n提醒：華而不實，終非長久之計。"),
    ("剝","山地","剝落衰退，去舊迎新。\n運勢：此時宜守不宜進。\n提醒：剝極而復，否極泰來。"),
    ("復","地雷","回復正道，重振旗鼓。\n運勢：低潮已過，好運即將到來。\n提醒：回頭是岸，重新出發。"),
    ("無妄","天雷","無妄之災，順天而行。\n運勢：凡事不可強求，順其自然。\n提醒：行正道，避橫禍。"),
    ("大畜","山天","大量積蓄，厚積薄發。\n運勢：積累已足，可大展宏圖。\n提醒：厚積薄發，時機成熟則行。"),
    ("頤","山雷","頤養正道，滋養身心。\n運勢：宜注重健康飲食。\n提醒：禍從口出，病從口入。"),
    ("大過","澤風","大有過失，力挽狂瀾。\n運勢：處境艱難，需奮力一搏。\n提醒：非常時期，需非常手段。"),
    ("坎","水","重重險阻，百折不撓。\n運勢：困難重重，堅持必能渡過。\n提醒：臨危不亂，沉著應對。"),
    ("離","火","光明磊落，文明昌盛。\n運勢：前途光明，才華得以發揮。\n提醒：光而不耀，謙遜為懷。"),
    ("咸","澤山","感應相通，男女相交。\n運勢：感情順遂，人際關係和諧。\n提醒：以誠相感，心靈相通。"),
    ("恆","雷風","持之以恆，永恆不變。\n運勢：堅持到底，必有所成。\n提醒：恆心是成功之母。"),
    ("遯","天山","隱退避世，以退為進。\n運勢：宜暫退一步，待機而動。\n提醒：退一步海闊天空。"),
    ("大壯","雷天","大而且壯，剛健有力。\n運勢：運勢旺盛，宜積極行動。\n提醒：壯而知止，方為大壯。"),
    ("晉","火地","晉升前進，光明在前。\n運勢：升遷有望，前途光明。\n提醒：穩步前進，勿躁進。"),
    ("明夷","地火","光明受損，韜光養晦。\n運勢：暫時受挫，宜低調行事。\n提醒：韜光養晦，等待時機。"),
    ("家人","風火","家庭和睦，各司其職。\n運勢：家庭和諧，事業順遂。\n提醒：家和萬事興。"),
    ("睽","火澤","乖違不合，分歧對立。\n運勢：易生誤解，溝通需加倍努力。\n提醒：求同存異，化解對立。"),
    ("蹇","水山","步履維艱，艱難前行。\n運勢：諸事不順，宜尋求外援。\n提醒：知難而退，另謀出路。"),
    ("解","雷水","解除困難，撥雲見日。\n運勢：困境解除，好運降臨。\n提醒：寬恕他人，廣結善緣。"),
    ("損","山澤","損下益上，節制自律。\n運勢：宜節制開支，量入為出。\n提醒：損之又損，以至於無為。"),
    ("益","風雷","增益補充，利人利己。\n運勢：諸事增益，財運亨通。\n提醒：取之有道，用之有節。"),
    ("夬","澤天","決斷去除，果斷行動。\n運勢：宜果斷決策，排除障礙。\n提醒：當斷則斷，勿留後患。"),
    ("姤","天風","邂逅相遇，機緣巧合。\n運勢：貴人相遇，機緣難得。\n提醒：把握緣分，珍惜相遇。"),
    ("萃","澤地","聚集匯萃，眾志成城。\n運勢：人氣旺盛，合作有成。\n提醒：團結力量大。"),
    ("升","地風","步步高升，循序漸進。\n運勢：事業上升，前途看好。\n提醒：一步一腳印，穩健上升。"),
    ("困","澤水","困頓之時，窮則思變。\n運勢：處境困難，需積極尋求突破。\n提醒：絕處逢生。"),
    ("井","水風","井養萬民，取之不盡。\n運勢：資源充足，宜與人分享。\n提醒：飲水思源，回饋社會。"),
    ("革","澤火","革故鼎新，改革創新。\n運勢：改革時機已到，勇於創新。\n提醒：革命需順天應人。"),
    ("鼎","火風","鼎新革故，烹調萬物。\n運勢：事業鼎盛，創新有成。\n提醒：以新換舊，與時俱進。"),
    ("震","雷","震動驚懼，奮發圖強。\n運勢：受到震撼，但能化危為機。\n提醒：臨危不懼，化險為夷。"),
    ("艮","山","止而不進，靜思內省。\n運勢：宜靜不宜動，深思熟慮。\n提醒：適時而止，方為明智。"),
    ("漸","風山","循序漸進，按部就班。\n運勢：事業漸入佳境，穩中求進。\n提醒：欲速則不達。"),
    ("歸妹","雷澤","嫁娶歸宿，終有所歸。\n運勢：感情有歸宿，但需謹慎。\n提醒：慎擇良緣，勿草率行事。"),
    ("豐","雷火","豐盛充實，盛極而衰。\n運勢：當前運勢旺盛，宜把握機會。\n提醒：盛極必衰，居安思危。"),
    ("旅","火山","旅途奔波，客居異鄉。\n運勢：適合旅行、出差，外出有利。\n提醒：在外謹慎，廣結善緣。"),
    ("巽","風","順風而行，柔順謙遜。\n運勢：順風順水，凡事順遂。\n提醒：過於柔順則失去主見。"),
    ("兌","澤","喜悅和樂，口才出眾。\n運勢：人際關係佳，口才助事業。\n提醒：悅人悅己，和氣生財。"),
    ("渙","風水","渙散離析，聚散無常。\n運勢：凡事易散，需加強凝聚力。\n提醒：散而後聚，整合資源。"),
    ("節","水澤","節制有度，適可而止。\n運勢：宜節制，不可過度放縱。\n提醒：節儉自律，方能長久。"),
    ("中孚","風澤","誠信為本，以誠感人。\n運勢：誠信行事，必得人心。\n提醒：一諾千金，誠信是金。"),
    ("小過","雷山","小有過失，謹小慎微。\n運勢：小事易成，大事宜謹慎。\n提醒：謹慎小心，勿犯小過。"),
    ("既濟","水火","已經成功，圓滿完成。\n運勢：諸事圓滿，但需防樂極生悲。\n提醒：成功後仍需謹慎維持。"),
    ("未濟","火水","尚未完成，繼續努力。\n運勢：事業尚未完成，需繼續努力。\n提醒：未竟之事，堅持到底。"),
]

def get_daily_hexagram(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    seed = hashlib.md5(f"{user_id}{today}".encode()).hexdigest()
    idx = int(seed[:8], 16) % 64
    return HEXAGRAMS[idx]

# ── Flask 路由 ────────────────────────────────────────
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
    """處理圖片訊息：OCR 辨識泰文/英文並翻譯成中文"""
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        try:
            # 下載圖片
            msg_content = line_bot_api.get_message_content(event.message.id)
            image_data = msg_content.read()

            # OCR 辨識並翻譯
            result = ocr_and_translate(image_data)
            if result is None or result[0] is None:
                reply_text = "⚠️ 無法辨識圖片中的文字，請確認圖片清晰且含有泰文或英文。"
            else:
                original, translated, lang = result
                # 截短原文避免太長
                short_orig = original[:200] + "..." if len(original) > 200 else original
                reply_text = (
                    f"🔍 辨識到{lang}：\n"
                    f"{short_orig}\n\n"
                    f"📖 中文翻譯：\n"
                    f"{translated}"
                )
        except Exception as e:
            reply_text = f"⚠️ 圖片處理失敗，請稍後再試。"

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
                        ImageMessage(
                            original_content_url=bts_map_url,
                            preview_image_url=bts_map_url,
                        ),
                        TextMessage(text=(
                            "🚈 BTS 路線圖\n"
                            "─────────────────\n"
                            "🟢 Sukhumvit Line（綠線）\n"
                            "Mo Chit ↔ Bearing / Kheha\n\n"
                            "🟢 Silom Line（深綠線）\n"
                            "National Stadium ↔ Bang Wa\n\n"
                            "傳「BTS 站名」查詢附近景點"
                        )),
                    ],
                )
            )
            return

        # 抽卦
        if user_text in ["抽卦", "抽籤", "運勢", "今日運勢", "卦象"]:
            name, nature, desc = get_daily_hexagram(user_id)
            today = datetime.now().strftime("%Y年%m月%d日")
            reply_text = (
                f"☯ {today} 今日卦象\n"
                f"{'─'*18}\n"
                f"【{name}卦】{nature}\n\n"
                f"{desc}\n"
                f"{'─'*18}\n"
                f"每日一卦，明日再抽"
            )

        # BTS 站點查詢
        elif "BTS" in user_text.upper() or "bts" in user_text.lower() or "捷運" in user_text or "站" in user_text:
            station_key = find_station(user_text)
            if station_key:
                reply_text = get_station_info(station_key)
            else:
                reply_text = (
                    "🚈 請輸入 BTS 站名查詢附近景點\n\n"
                    "例如：\n"
                    "「BTS Siam」「暹羅站」\n"
                    "「BTS Asok」「阿速站」\n"
                    "「BTS Thong Lo」「通羅站」"
                )

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
                        "功能選單：\n"
                        "🔤 傳中文 → 翻譯成泰文\n"
                        "🔤 傳泰文 → 翻譯成中文\n"
                        "🖼 傳圖片 → 辨識泰文/英文翻譯\n"
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
