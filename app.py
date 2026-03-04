# Credit @JOBAYAR_AHMED
# Join @GHOST_XAPIS
from flask import Flask, jsonify, request
import aiohttp
import asyncio
import json
from byte import encrypt_api, Encrypt_ID
from visit_count_pb2 import Info  # Import the generated protobuf class

app = Flask(__name__)

# Global variables for token routing
token_rotation = {}
TOKENS_PER_REQUEST = 20

def load_all_tokens(server_name):
    try:
        if server_name == "IND":
            path = "token_ind.json"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            path = "token_br.json"
        else:
            path = "token_bd.json"

        with open(path, "r") as f:
            data = json.load(f)

        tokens = [item["token"] for item in data if "token" in item and item["token"] not in ["", "N/A"]]
        return tokens
    except Exception as e:
        app.logger.error(f"❌ Token load error for {server_name}: {e}")
        return []

def get_tokens_for_request(server_name):
    global token_rotation
    
    if server_name not in token_rotation:
        all_tokens = load_all_tokens(server_name)
        token_rotation[server_name] = {
            'all_tokens': all_tokens,
            'current_index': 0,
            'total_tokens': len(all_tokens)
        }
    
    rotation_data = token_rotation[server_name]
    all_tokens = rotation_data['all_tokens']
    current_index = rotation_data['current_index']
    total_tokens = rotation_data['total_tokens']
    
    if total_tokens == 0:
        return []
    
    # Calculate tokens for this request
    start_index = current_index
    end_index = (current_index + TOKENS_PER_REQUEST) % total_tokens
    
    if start_index < end_index:
        tokens_for_request = all_tokens[start_index:end_index]
    else:
        # Handle wrap-around case
        tokens_for_request = all_tokens[start_index:] + all_tokens[:end_index]
    
    # Update rotation index for next request
    token_rotation[server_name]['current_index'] = end_index
    
    print(f"🔑 Token rotation for {server_name}: Using tokens {start_index+1}-{end_index if end_index > start_index else total_tokens} (Total: {total_tokens})")
    
    return tokens_for_request

def get_url(server_name):
    if server_name == "IND":
        return "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
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
        "ReleaseVersion": "OB52",
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
            # Use only the allocated tokens for this request
            available_tokens = tokens
            if not available_tokens:
                break
                
            batch_size = min(target_success - total_success, TOKENS_PER_REQUEST)
            tasks = [
                asyncio.create_task(visit(session, url, available_tokens[i % len(available_tokens)], uid, data))
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

            print(f"🔑 Using {len(available_tokens)} tokens | Batch sent: {batch_size}, Success in batch: {batch_success}, Total success so far: {total_success}")

    return total_success, total_sent, player_info

@app.route('/visit', methods=['GET'])
def send_visits():
    # Get parameters from query string
    region = request.args.get('region', '').upper()
    uid = request.args.get('uid', '')
    
    if not region or not uid:
        return jsonify({"error": "Missing required parameters: region and uid"}), 400
    
    try:
        uid = int(uid)
    except ValueError:
        return jsonify({"error": "UID must be a valid number"}), 400
    
    # Get tokens for this specific request using rotation system
    tokens = get_tokens_for_request(region)
    target_success = 1000

    if not tokens:
        return jsonify({"error": "❌ No valid tokens found for this region"}), 500

    print(f"🚀 Sending visits to UID: {uid} in region: {region} using {len(tokens)} tokens (Token Rotation System)")
    print(f"🔑 Token batch: {tokens[:3]}...")  # Show first 3 tokens for debugging
    print(f"Waiting for total {target_success} successful visits...")

    total_success, total_sent, player_info = asyncio.run(send_until_1000_success(
        tokens, uid, region,
        target_success=target_success
    ))

    if player_info:
        player_info_response = {
            "fail": target_success - total_success,
            "level": player_info.get("level", 0),
            "likes": player_info.get("likes", 0),
            "nickname": player_info.get("nickname", ""),
            "region": player_info.get("region", ""),
            "success": total_success,
            "uid": player_info.get("uid", 0),
            "tokens_used": len(tokens),
            "token_rotation": "active"
        }
        return jsonify(player_info_response), 200
    else:
        return jsonify({"error": "Could not decode player information"}), 500

@app.route('/token-status/<string:server>', methods=['GET'])
def token_status(server):
    server = server.upper()
    
    if server in token_rotation:
        rotation_data = token_rotation[server]
        return jsonify({
            "server": server,
            "total_tokens": rotation_data['total_tokens'],
            "current_index": rotation_data['current_index'],
            "tokens_per_request": TOKENS_PER_REQUEST,
            "next_batch_start": rotation_data['current_index'],
            "next_batch_end": (rotation_data['current_index'] + TOKENS_PER_REQUEST) % rotation_data['total_tokens']
        })
    else:
        return jsonify({"error": "No tokens loaded for this server"}), 404

if __name__ == "__main__":
    print(f"🔑 Token Rotation System Activated")
    print(f"🔑 Each request will use {TOKENS_PER_REQUEST} tokens")
    print(f"🌐 API Endpoint: http://0.0.0.0:5000")
    print(f"🔑 Server running on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5070)


# Credit @JOBAYAR_AHMED
# Join @GHOST_XAPIS