from flask import Flask, request, jsonify, make_response, render_template
from flask_cors import CORS
import json
import math
import os
import requests
from datetime import datetime

app = Flask(__name__)
CORS(app)  # habilita CORS para todas as rotas

GITHUB_OWNER = "vitcas"
GITHUB_REPO = "onepiece-api"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/commits"
# garante que o arquivo JSON seja lido mesmo no ambiente serverless
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(BASE_DIR, "..", "onepiece_cards.json")

with open(JSON_PATH, "r", encoding="utf-8") as f:
    ONEPIECE_CARDS = json.load(f)

@app.route("/")
def root():
    base_url = request.host_url.rstrip("/")
    endpoints = [
        {"name": "Listar cartas", "url": f"{base_url}/cards?name=luffy"},
        {"name": "Buscar carta por código/id/nome", "url": f"{base_url}/card/OP05-119"},
        {"name": "Listar sets", "url": f"{base_url}/sets"},
        {"name": "Listar cartas do set", "url": f"{base_url}/set/17675"},
        {"name": "Última modificação do JSON", "url": f"{base_url}/last-modified"}
    ]
    return render_template("home.html", endpoints=endpoints)

@app.route("/last-modified")
def last_modified_github():
    try:
        # você pode querer usar autenticação se tiver limites de requisição
        resp = requests.get(GITHUB_API_URL, params={"per_page": 1})
        resp.raise_for_status()
        commits = resp.json()
        if not commits:
            return jsonify({"error": "No commits found"}), 404

        latest = commits[0]
        # a data do commit do “committer” costuma refletir quando foi realmente gravado (push) no GitHub
        # você pode também usar latest["commit"]["author"]["date"], dependendo do que quiser exibir
        date = latest["commit"]["committer"]["date"]
        return jsonify({"lastModified": date})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/cards")
def get_cards():
    filters = {
        "id": request.args.get("id"),
        "code": request.args.get("code"),
        "rarity": request.args.get("rarity"),
        "type": request.args.get("type"),
        "name": request.args.get("name"),
        "cost": request.args.get("cost"),
        "power": request.args.get("power"),
        "counter": request.args.get("counter"),
        "color": request.args.get("color"),
        "family": request.args.get("family"),
        "ability": request.args.get("ability"),
        "trigger": request.args.get("trigger"),
    }

    set_gid = request.args.get("set_groupId")
    multi_variant = request.args.get("multi_variant")

    filtered = []
    for card in ONEPIECE_CARDS:
        match = True
        for field, value in filters.items():
            if value:
                card_val = str(card.get(field, "")).lower()
                if str(value).lower() not in card_val:
                    match = False
                    break

        if match and set_gid:
            card_set_gid = str(card.get("set", {}).get("groupId", ""))
            if card_set_gid != str(set_gid):
                match = False

        if match and multi_variant:
            if not card.get("variants") or len(card["variants"]) <= 1:
                match = False

        if match:
            filtered.append(card)

    try:
        limit = min(int(request.args.get("limit", 25)), 100)
    except ValueError:
        limit = 25
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except ValueError:
        page = 1

    total = len(filtered)
    total_pages = math.ceil(total / limit) if limit > 0 else 1

    start = (page - 1) * limit
    end = start + limit
    paginated = filtered[start:end]

    return jsonify({
        "page": page,
        "limit": limit,
        "total": total,
        "totalPages": total_pages,
        "data": paginated
    })

@app.route("/card/<value>")
def get_card(value):
    value = value.lower()
    for card in ONEPIECE_CARDS:
        if str(card.get("id", "")).lower() == value or str(card.get("code", "")).lower() == value:
            return jsonify(card)
    return jsonify({"error": "Card not found"}), 404

@app.route("/sets")
def get_sets():
    sets_dict = {}

    for card in ONEPIECE_CARDS:
        set_info = card.get("set")
        if not set_info or "groupId" not in set_info:
            continue

        gid = set_info["groupId"]

        # inicializa o set se ainda não existir
        if gid not in sets_dict:
            sets_dict[gid] = {
                **set_info,
                "card_count": 0
            }

        sets_dict[gid]["card_count"] += 1

        # caso especial: groupId 17675 → guardar todos os "names" distintos
        if gid == 17675:
            if "names" not in sets_dict[gid]:
                sets_dict[gid]["names"] = set()
            name_val = set_info.get("name")
            if name_val:
                sets_dict[gid]["names"].add(name_val)

    # converter names (set → lista)
    for s in sets_dict.values():
        if "names" in s:
            s["names"] = sorted(list(s["names"]))

    # ordena por set_code (alfabético)
    sets_list = sorted(
        sets_dict.values(),
        key=lambda x: (x.get("set_code") or "").lower()
    )

    return jsonify(sets_list)

@app.route("/set/<group_id>")
def get_set_cards(group_id):
    # condição especial: 17675 → inclui todas as variações dentro do mesmo grupo
    if str(group_id) == "17675":
        filtered = [
            card for card in ONEPIECE_CARDS
            if str(card.get("set", {}).get("groupId", "")) == "17675"
        ]
    else:
        filtered = [
            card for card in ONEPIECE_CARDS
            if str(card.get("set", {}).get("groupId", "")) == str(group_id)
        ]

    if not filtered:
        return jsonify({"error": f"No cards found for set groupId '{group_id}'"}), 404

    # ordena por código (para consistência)
    filtered.sort(key=lambda c: (c.get("code") or "").lower())

    total = len(filtered)
    limit = total  # mostra todas as cartas disponíveis
    page = 1
    total_pages = 1

    return jsonify({
        "groupId": group_id,
        "page": page,
        "limit": limit,
        "total": total,
        "totalPages": total_pages,
        "data": filtered
    })

@app.after_request
def add_cache_headers(resp):
    resp.headers["Cache-Control"] = "s-maxage=300, stale-while-revalidate=600"
    return resp
    
# não precisa de app.run() – o Vercel já usa a variável app
if __name__ == "__main__":
    #app.run(debug=True)
    app.run(port=5001, debug=True)
