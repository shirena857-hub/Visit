# Credit @JOBAYAR_AHMED
# Join @GHOST_XAPIS
from flask import Flask, jsonify, request
import aiohttp
import asyncio
import json
import os
from byte import encrypt_api, Encrypt_ID
from visit_count_pb2 import Info  # Import the generated protobuf class

app = Flask(__name__)

# Global variables for token routing
token_rotation = {}
TOKENS_PER_REQUEST = 20

# ---------------------------
# Dynamic token fetching (like the reference API)
# ---------------------------
ACCOUNTS_FILE = 'accounts.json'

def load_accounts():
    """Load uid:password pairs from accounts.json"""
    if os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, 'r') as f:
            return json.load(f)
    return {}

async def fetch_token(session, uid, password):
    """Fetch a single JWT from the external API"""
    url = f"https://jwt-amber-three.vercel.app/token?uid={uid}&password={password}"
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status == 200:
                text = await resp.text()
                try:
                    data = json.loads(text)
                    if isinstance(data, list) and len(data) > 0 and "token" in data[0]:
                        return data[0]["token"]
                    elif isinstance(data, dict) and "token" in data:
                        return data["token"]
                except:
                    return None
    except:
        return None
    return None

async def get_tokens_live():
    """Fetch tokens for all accounts in accounts.json"""
    accounts = load_accounts()
    if not accounts:
        print("⚠️ No accounts found in accounts.json")
        return []
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_token(session, uid, pwd) for uid, pwd in accounts.items()]
        results = await asyncio.gather(*tasks)
        tokens = [t for t in results if t]
        print(f"✅ Fetched {len(tokens)} live tokens")
        return tokens

# ---------------------------
# Original visit logic (unchanged)
# ---------------------------
def get_url(server_name):
    if server_name == "BD":
        return "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow"
    elif server_name in {"BR", "US", "SAC", "NA"}:
        return "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    else:
        return "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"

def parse_protobuf_response(response_data):
    try:
        info = Info()
        info.ParseFromString(response_data)
        player_data = {
            "uid": info.AccountInfo.UID if info.AccountInfo.UID else 0,
            "nickname": info.AccountInfo.PlayerNickname if info.AccountInfo.PlayerNickname else "",
            "likes": info.AccountInfo.Likes if info.AccountInfo.Likes else 0,
            "region": info.AccountInfo.PlayerRegion if info.AccountInfo.PlayerRegion else "",
            "level": info.AccountInfo.Levels if info.AccountInfo.Levels else 0
        }
        return player_data
    except Exception as e:
        app.logger.error(f"❌ Protobuf parsing error: {e}")
        return None

async def visit(session, url, token, uid, data):
    headers = {
        "ReleaseVersion": "OB53",
        "X-GA": "v1 1",
        "Authorization": f"Bearer {token}",
        "Host": url.replace("https://", "").split("/")[0]
    }
    try:
        async with session.post(url, headers=headers, data=data, ssl=False) as resp:
            if resp.status == 200:
                response_data = await resp.read()
                return True, response_data
            else:
                return False, None
    except Exception as e:
        app.logger.error(f"❌ Visit error: {e}")
        return False, None

async def send_until_1000_success(tokens, uid, server_name, target_success=1000):
    url = get_url(server_name)
    connector = aiohttp.TCPConnector(limit=0)
    total_success = 0
    total_sent = 0
    first_success_response = None
    player_info = None

    async with aiohttp.ClientSession(connector=connector) as session:
        encrypted = encrypt_api("08" + Encrypt_ID(str(uid)) + "1801")
        data = bytes.fromhex(encrypted)

        while total_success < target_success:
            if not tokens:
                break
            batch_size = min(target_success - total_success, TOKENS_PER_REQUEST)
            tasks = [
                asyncio.create_task(visit(session, url, tokens[i % len(tokens)], uid, data))
                for i in range(batch_size)
            ]
            results = await asyncio.gather(*tasks)

            if first_success_response is None:
                for success, response in results:
                    if success and response is not None:
                        first_success_response = response
                        player_info = parse_protobuf_response(response)
                        break

            batch_success = sum(1 for r, _ in results if r)
            total_success += batch_success
            total_sent += batch_size

            print(f"🔑 Using {len(tokens)} tokens | Batch sent: {batch_size}, Success: {batch_success}, Total success: {total_success}")

    return total_success, total_sent, player_info

# ---------------------------
# Flask endpoints
# ---------------------------
@app.route('/visit', methods=['GET'])
def send_visits():
    region = request.args.get('region', '').upper()
    uid = request.args.get('uid', '')

    if not region or not uid:
        return jsonify({"error": "Missing required parameters: region and uid"}), 400
    try:
        uid = int(uid)
    except ValueError:
        return jsonify({"error": "UID must be a valid number"}), 400

    # 🔥 Get live tokens instead of reading from JSON files
    tokens = asyncio.run(get_tokens_live())
    if not tokens:
        return jsonify({"error": "❌ No valid tokens fetched. Check accounts.json and network."}), 500

    target_success = 1000
    print(f"🚀 Sending visits to UID: {uid} in region: {region} using {len(tokens)} live tokens")
    print(f"🔑 First 3 tokens: {tokens[:3]}...")
    print(f"🎯 Target: {target_success} successful visits")

    total_success, total_sent, player_info = asyncio.run(send_until_1000_success(
        tokens, uid, region, target_success=target_success
    ))

    if player_info:
        response = {
            "fail": target_success - total_success,
            "level": player_info.get("level", 0),
            "likes": player_info.get("likes", 0),
            "nickname": player_info.get("nickname", ""),
            "region": player_info.get("region", ""),
            "success": total_success,
            "uid": player_info.get("uid", 0),
            "tokens_used": len(tokens),
            "token_source": "live_jwt_api"
        }
        return jsonify(response), 200
    else:
        return jsonify({"error": "Could not decode player information"}), 500

@app.route('/token-status', methods=['GET'])
def token_status():
    """Returns the number of live tokens fetched last time (no static storage)"""
    return jsonify({
        "message": "Tokens are fetched live from accounts.json on each request",
        "status": "dynamic"
    })

if __name__ == "__main__":
    print(f"🔑 Live JWT Auto‑Generation Activated")
    print(f"📁 Using accounts from {ACCOUNTS_FILE}")
    print(f"🔑 Each request will fetch fresh tokens and use {TOKENS_PER_REQUEST} per batch")
    print(f"🌐 API Endpoint: http://0.0.0.0:5070")
    app.run(host="0.0.0.0", port=5070)
