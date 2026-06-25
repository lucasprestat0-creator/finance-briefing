import anthropic
import resend
import json
import os
import re
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────────────────────────
RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
RESEND_API_KEY = os.environ["RESEND_API_KEY"]
# ──────────────────────────────────────────────────────────────────────────────

resend.api_key = RESEND_API_KEY
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

today = datetime.now().strftime("%d/%m/%Y")
today_iso = datetime.now().strftime("%Y-%m-%d")

# ─── ÉTAPE 1 : RECHERCHE WEB ──────────────────────────────────────────────────
print("🔍 Recherche des actualités financières...")

search_prompt = f"""Date d'aujourd'hui : {today}
Recherche les actualités financières du jour :
1. Les variations des marchés boursiers (CAC 40, S&P 500, Nikkei, DAX, Hang Seng)
2. Les événements géopolitiques impactant les marchés
3. Les opportunités d'investissement du moment
Fais plusieurs recherches pour couvrir tous ces sujets."""

search_response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4000,
    tools=[{"type": "web_search_20250305", "name": "web_search"}],
    messages=[{"role": "user", "content": search_prompt}]
)

# Reconstruire l'historique complet pour la synthèse
messages_history = [
    {"role": "user", "content": search_prompt},
    {"role": "assistant", "content": search_response.content}
]

print("✅ Recherches effectuées")

# ─── ÉTAPE 2 : GÉNÉRATION DU JSON ─────────────────────────────────────────────
print("📝 Génération du briefing...")

json_instruction = f"""Parfait. Maintenant génère le briefing financier quotidien au format JSON strict.
Réponds UNIQUEMENT avec le JSON ci-dessous, sans aucun texte avant ou après, sans markdown, sans backticks.
Tous les champs sont OBLIGATOIRES, y compris "a_surveiller" qui doit contenir au moins 3 éléments.

{{
  "date": "{today}",
  "headline": "Titre accrocheur du jour en une phrase",
  "marches": {{
    "resume": "2-3 phrases de synthèse des marchés hier",
    "variations": [
      {{"indice": "CAC 40", "variation": "+0.8%", "commentaire": "contexte"}},
      {{"indice": "S&P 500", "variation": "-0.3%", "commentaire": "contexte"}},
      {{"indice": "Nikkei", "variation": "+1.2%", "commentaire": "contexte"}},
      {{"indice": "DAX", "variation": "+0.5%", "commentaire": "contexte"}},
      {{"indice": "Hang Seng", "variation": "-0.7%", "commentaire": "contexte"}}
    ],
    "secteur_focus": "Secteur à surveiller aujourd'hui et pourquoi"
  }},
  "geopolitique": {{
    "resume": "Synthèse des tensions géopolitiques ayant un impact marché",
    "evenements": [
      {{"zone": "Zone/conflit", "situation": "Description courte", "impact_marche": "Impact concret"}},
      {{"zone": "Zone/conflit", "situation": "Description courte", "impact_marche": "Impact concret"}}
    ]
  }},
  "opportunites": {{
    "intro": "Phrase d'intro sur le contexte du jour",
    "idees": [
      {{"titre": "Titre", "type": "Action", "raisonnement": "Pourquoi maintenant", "risques": "Risques"}},
      {{"titre": "Titre", "type": "ETF", "raisonnement": "Pourquoi maintenant", "risques": "Risques"}},
      {{"titre": "Titre", "type": "Matière première", "raisonnement": "Pourquoi maintenant", "risques": "Risques"}}
    ],
    "disclaimer": "Ceci est purement spéculatif et ne constitue pas un conseil en investissement."
  }},
  "a_surveiller": [
    "Événement 1",
    "Événement 2",
    "Événement 3"
  ]
}}"""

messages_history.append({"role": "user", "content": json_instruction})


def request_json(messages):
    """Appelle le modèle et renvoie le texte brut de la réponse."""
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,  # relevé pour éviter la troncature du JSON (a_surveiller est en fin)
        system="Tu es un analyste financier senior. Tu réponds UNIQUEMENT avec du JSON valide, sans aucun texte autour, sans markdown.",
        messages=messages
    )
    text = ""
    for block in resp.content:
        if block.type == "text":
            text += block.text
    return text


def extract_json(raw_text):
    """Nettoie et parse le JSON. Renvoie un dict, ou None si échec."""
    cleaned = re.sub(r"```json|```", "", raw_text).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


# Tentative + 1 retry si le JSON est invalide
raw_text = request_json(messages_history)
data = extract_json(raw_text)

if data is None:
    print("⚠️ JSON invalide, nouvelle tentative...")
    messages_history.append({"role": "assistant", "content": raw_text})
    messages_history.append({
        "role": "user",
        "content": "Ta réponse précédente n'était pas un JSON valide. Renvoie UNIQUEMENT le JSON complet et valide, sans aucun texte ni markdown."
    })
    raw_text = request_json(messages_history)
    data = extract_json(raw_text)

if data is None:
    print("❌ Impossible d'obtenir un JSON valide après 2 tentatives.")
    print("Réponse brute :\n", raw_text[:2000])
    raise SystemExit(1)


# ─── NORMALISATION : garantit que tout le schéma existe ───────────────────────
def normalize_data(d):
    """Remplit chaque champ manquant avec une valeur par défaut.
    Après ce passage, build_email ne peut plus lever de KeyError."""
    if not isinstance(d, dict):
        d = {}

    d.setdefault("date", today)
    d.setdefault("headline", "Briefing financier du jour")

    # --- marchés ---
    marches = d.get("marches") if isinstance(d.get("marches"), dict) else {}
    marches.setdefault("resume", "Synthèse des marchés indisponible aujourd'hui.")
    marches.setdefault("secteur_focus", "—")
    variations = marches.get("variations")
    variations = variations if isinstance(variations, list) else []
    marches["variations"] = [
        {
            "indice": v.get("indice", "—"),
            "variation": v.get("variation", "n/a"),
            "commentaire": v.get("commentaire", ""),
        }
        for v in variations if isinstance(v, dict)
    ]
    d["marches"] = marches

    # --- géopolitique ---
    geo = d.get("geopolitique") if isinstance(d.get("geopolitique"), dict) else {}
    geo.setdefault("resume", "")
    evenements = geo.get("evenements")
    evenements = evenements if isinstance(evenements, list) else []
    geo["evenements"] = [
        {
            "zone": e.get("zone", "—"),
            "situation": e.get("situation", ""),
            "impact_marche": e.get("impact_marche", ""),
        }
        for e in evenements if isinstance(e, dict)
    ]
    d["geopolitique"] = geo

    # --- opportunités ---
    opp = d.get("opportunites") if isinstance(d.get("opportunites"), dict) else {}
    opp.setdefault("intro", "")
    opp.setdefault(
        "disclaimer",
        "Ceci est purement spéculatif et ne constitue pas un conseil en investissement."
    )
    idees = opp.get("idees")
    idees = idees if isinstance(idees, list) else []
    opp["idees"] = [
        {
            "titre": o.get("titre", "—"),
            "type": o.get("type", "Autre"),
            "raisonnement": o.get("raisonnement", ""),
            "risques": o.get("risques", ""),
        }
        for o in idees if isinstance(o, dict)
    ]
    d["opportunites"] = opp

    # --- à surveiller ---
    a_surveiller = d.get("a_surveiller")
    a_surveiller = a_surveiller if isinstance(a_surveiller, list) else []
    d["a_surveiller"] = [str(s) for s in a_surveiller]

    return d


data = normalize_data(data)
print("✅ Briefing généré")


# ─── TEMPLATE EMAIL HTML ──────────────────────────────────────────────────────
def build_email(d):
    variations_html = ""
    for v in d["marches"]["variations"]:
        color = "#16a34a" if "+" in v["variation"] else "#dc2626"
        variations_html += f"""
        <tr>
          <td style="padding:8px 12px;font-weight:600">{v['indice']}</td>
          <td style="padding:8px 12px;color:{color};font-weight:700">{v['variation']}</td>
          <td style="padding:8px 12px;color:#6b7280">{v['commentaire']}</td>
        </tr>"""

    geo_html = ""
    for e in d["geopolitique"]["evenements"]:
        geo_html += f"""
        <div style="border-left:3px solid #f59e0b;padding:10px 14px;margin:10px 0;background:#fffbeb">
          <strong style="color:#92400e">{e['zone']}</strong><br>
          <span style="color:#374151">{e['situation']}</span><br>
          <span style="color:#6b7280;font-size:13px">📊 Impact : {e['impact_marche']}</span>
        </div>"""

    opps_html = ""
    type_colors = {"Action":"#3b82f6","ETF":"#8b5cf6","Obligation":"#10b981","Matière première":"#f59e0b","Crypto":"#ec4899"}
    for i, o in enumerate(d["opportunites"]["idees"], 1):
        color = type_colors.get(o["type"], "#6b7280")
        opps_html += f"""
        <div style="border:1px solid #e5e7eb;border-radius:8px;padding:14px;margin:10px 0">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
            <span style="background:{color};color:white;padding:2px 8px;border-radius:12px;font-size:12px">{o['type']}</span>
            <strong style="color:#111827">{o['titre']}</strong>
          </div>
          <p style="color:#374151;margin:4px 0">💡 {o['raisonnement']}</p>
          <p style="color:#dc2626;margin:4px 0;font-size:13px">⚠️ Risques : {o['risques']}</p>
        </div>"""

    surveiller_html = "".join(
        f"<li style='margin:6px 0;color:#374151'>{s}</li>" for s in d["a_surveiller"]
    )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f3f4f6;margin:0;padding:20px">
  <div style="max-width:680px;margin:0 auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 6px rgba(0,0,0,0.07)">
    <div style="background:linear-gradient(135deg,#1e3a5f,#2563eb);padding:28px 32px">
      <div style="color:#93c5fd;font-size:13px;text-transform:uppercase;letter-spacing:1px">Briefing Financier Quotidien</div>
      <h1 style="color:white;margin:8px 0 4px;font-size:22px">{d['headline']}</h1>
      <div style="color:#bfdbfe;font-size:14px">{d['date']}</div>
    </div>
    <div style="padding:24px 32px">
      <h2 style="color:#1e3a5f;border-bottom:2px solid #dbeafe;padding-bottom:8px">📈 Marchés</h2>
      <p style="color:#374151">{d['marches']['resume']}</p>
      <table style="width:100%;border-collapse:collapse;margin:12px 0">
        <thead><tr style="background:#f8fafc">
          <th style="padding:8px 12px;text-align:left;color:#6b7280;font-size:13px">Indice</th>
          <th style="padding:8px 12px;text-align:left;color:#6b7280;font-size:13px">Variation</th>
          <th style="padding:8px 12px;text-align:left;color:#6b7280;font-size:13px">Contexte</th>
        </tr></thead>
        <tbody>{variations_html}</tbody>
      </table>
      <div style="background:#eff6ff;border-radius:8px;padding:12px 16px;margin-top:12px">
        <strong style="color:#1d4ed8">🔍 Secteur focus :</strong>
        <span style="color:#374151"> {d['marches']['secteur_focus']}</span>
      </div>
      <h2 style="color:#1e3a5f;border-bottom:2px solid #dbeafe;padding-bottom:8px;margin-top:28px">🌍 Contexte Géopolitique</h2>
      <p style="color:#374151">{d['geopolitique']['resume']}</p>
      {geo_html}
      <h2 style="color:#1e3a5f;border-bottom:2px solid #dbeafe;padding-bottom:8px;margin-top:28px">💼 Opportunités du Jour</h2>
      <p style="color:#374151">{d['opportunites']['intro']}</p>
      {opps_html}
      <p style="color:#9ca3af;font-size:12px;font-style:italic">{d['opportunites']['disclaimer']}</p>
      <h2 style="color:#1e3a5f;border-bottom:2px solid #dbeafe;padding-bottom:8px;margin-top:28px">⏰ À Surveiller Aujourd'hui</h2>
      <ul style="padding-left:20px">{surveiller_html}</ul>
    </div>
    <div style="background:#f8fafc;padding:16px 32px;text-align:center;color:#9ca3af;font-size:12px">
      Finance Briefing — Généré automatiquement par IA · <a href="https://lucasprestat0.github.io/finance-briefing" style="color:#3b82f6">Voir l'archive</a>
    </div>
  </div>
</body>
</html>"""

html_content = build_email(data)

# ─── ENVOI EMAIL ──────────────────────────────────────────────────────────────
print("📧 Envoi de l'email...")
resend.Emails.send({
    "from": "Finance Briefing <onboarding@resend.dev>",
    "to": RECIPIENT_EMAIL,
    "subject": f"📊 {data['headline']} — {today}",
    "html": html_content
})
print("✅ Email envoyé")

# ─── SAUVEGARDE GITHUB PAGES ──────────────────────────────────────────────────
os.makedirs("docs/editions", exist_ok=True)

with open(f"docs/editions/{today_iso}.html", "w", encoding="utf-8") as f:
    f.write(html_content)

editions = sorted([
    f.replace(".html", "")
    for f in os.listdir("docs/editions")
    if f.endswith(".html")
], reverse=True)

index_links = ""
for e in editions:
    dt = datetime.strptime(e, "%Y-%m-%d")
    label = dt.strftime("%d %B %Y")
    index_links += f'<li><a href="editions/{e}.html" style="color:#2563eb;text-decoration:none">📄 {label}</a></li>\n'

index_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Finance Briefing — Archive</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f3f4f6;padding:40px 20px}}
    .container{{max-width:600px;margin:0 auto;background:white;border-radius:12px;padding:32px;box-shadow:0 4px 6px rgba(0,0,0,0.07)}}
    h1{{color:#1e3a5f;margin-bottom:8px}}
    p{{color:#6b7280}}
    ul{{list-style:none;padding:0}}
    li{{padding:12px 0;border-bottom:1px solid #f3f4f6}}
    li:last-child{{border-bottom:none}}
    a:hover{{text-decoration:underline}}
  </style>
</head>
<body>
  <div class="container">
    <h1>📊 Finance Briefing</h1>
    <p>Archive des éditions quotidiennes</p>
    <ul>{index_links}</ul>
  </div>
</body>
</html>"""

with open("docs/index.html", "w", encoding="utf-8") as f:
    f.write(index_html)

print("✅ Pages GitHub mises à jour")
print("🎉 Briefing du jour terminé !")
