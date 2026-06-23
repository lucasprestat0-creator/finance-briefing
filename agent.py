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

SYSTEM_PROMPT = """Tu es un analyste financier senior spécialisé dans les marchés mondiaux.
Tu produis chaque matin un briefing financier complet, précis et actionnable.
Tu dois impérativement varier les sujets chaque jour : ne jamais répéter les mêmes thèmes, 
creuser des angles différents, explorer des secteurs, des géographies ou des actifs variés.
Tu réponds UNIQUEMENT en JSON valide, sans markdown, sans texte autour."""

USER_PROMPT = f"""Date d'aujourd'hui : {today}

Génère un briefing financier quotidien structuré en JSON avec exactement ce format :

{{
  "date": "{today}",
  "headline": "Titre accrocheur du jour en une phrase",
  "marches": {{
    "resume": "2-3 phrases de synthèse des marchés hier",
    "variations": [
      {{"indice": "CAC 40", "variation": "+0.8%", "commentaire": "porté par..."}},
      {{"indice": "S&P 500", "variation": "-0.3%", "commentaire": "..."}},
      {{"indice": "Nikkei", "variation": "+1.2%", "commentaire": "..."}},
      {{"indice": "DAX", "variation": "+0.5%", "commentaire": "..."}},
      {{"indice": "Hang Seng", "variation": "-0.7%", "commentaire": "..."}}
    ],
    "secteur_focus": "Un secteur en particulier à surveiller aujourd'hui et pourquoi"
  }},
  "geopolitique": {{
    "resume": "Synthèse des tensions géopolitiques ayant un impact marché",
    "evenements": [
      {{"zone": "Nom de la zone/conflit", "situation": "Description courte", "impact_marche": "Impact concret sur les prix/indices"}},
      {{"zone": "...", "situation": "...", "impact_marche": "..."}}
    ]
  }},
  "opportunites": {{
    "intro": "Phrase d'intro sur le contexte du jour pour les opportunités",
    "idees": [
      {{"titre": "Titre de l'opportunité", "type": "Action/ETF/Obligation/Matière première/Crypto", "raisonnement": "Pourquoi maintenant, quels catalyseurs", "risques": "Principaux risques à surveiller"}},
      {{"titre": "...", "type": "...", "raisonnement": "...", "risques": "..."}},
      {{"titre": "...", "type": "...", "raisonnement": "...", "risques": "..."}}
    ],
    "disclaimer": "Ceci est purement spéculatif et ne constitue pas un conseil en investissement."
  }},
  "a_surveiller": [
    "Événement ou publication à surveiller aujourd'hui 1",
    "Événement ou publication à surveiller aujourd'hui 2",
    "Événement ou publication à surveiller aujourd'hui 3"
  ]
}}

Sois précis, varié, et ancré dans l'actualité du jour. Explore des angles originaux."""

print("🔍 Appel à Claude avec web search...")

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4000,
    system=SYSTEM_PROMPT,
    tools=[{"type": "web_search_20250305", "name": "web_search"}],
    messages=[{"role": "user", "content": USER_PROMPT}]
)

# Extraire le texte JSON de la réponse (ignorer les blocs tool_use/tool_result)
raw_text = ""
for block in response.content:
    if block.type == "text":
        raw_text += block.text

# Si la réponse est vide (Claude a fait du web search sans texte final),
# relancer avec l'historique complet pour obtenir la synthèse
if not raw_text.strip():
    print("⚠️  Pas de texte final, relance avec historique...")
    messages = [{"role": "user", "content": USER_PROMPT}]
    
    # Construire l'historique avec les résultats de recherche
    assistant_content = response.content
    messages.append({"role": "assistant", "content": assistant_content})
    messages.append({"role": "user", "content": "Maintenant génère le briefing JSON complet en utilisant les résultats de recherche ci-dessus. Réponds UNIQUEMENT avec le JSON, sans markdown."})
    
    response2 = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    raw_text = ""
    for block in response2.content:
        if block.type == "text":
            raw_text += block.text

# Nettoyer et parser le JSON
raw_text = re.sub(r"```json|```", "", raw_text).strip()

# Extraire le JSON si entouré d'autre texte
json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
if json_match:
    raw_text = json_match.group(0)

data = json.loads(raw_text)

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

    surveiller_html = "".join(f"<li style='margin:6px 0;color:#374151'>{s}</li>" for s in d["a_surveiller"])

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f3f4f6;margin:0;padding:20px">
  <div style="max-width:680px;margin:0 auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 6px rgba(0,0,0,0.07)">

    <!-- HEADER -->
    <div style="background:linear-gradient(135deg,#1e3a5f,#2563eb);padding:28px 32px">
      <div style="color:#93c5fd;font-size:13px;text-transform:uppercase;letter-spacing:1px">Briefing Financier Quotidien</div>
      <h1 style="color:white;margin:8px 0 4px;font-size:22px">{d['headline']}</h1>
      <div style="color:#bfdbfe;font-size:14px">{d['date']}</div>
    </div>

    <div style="padding:24px 32px">

      <!-- MARCHÉS -->
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

      <!-- GÉOPOLITIQUE -->
      <h2 style="color:#1e3a5f;border-bottom:2px solid #dbeafe;padding-bottom:8px;margin-top:28px">🌍 Contexte Géopolitique</h2>
      <p style="color:#374151">{d['geopolitique']['resume']}</p>
      {geo_html}

      <!-- OPPORTUNITÉS -->
      <h2 style="color:#1e3a5f;border-bottom:2px solid #dbeafe;padding-bottom:8px;margin-top:28px">💼 Opportunités du Jour</h2>
      <p style="color:#374151">{d['opportunites']['intro']}</p>
      {opps_html}
      <p style="color:#9ca3af;font-size:12px;font-style:italic">{d['opportunites']['disclaimer']}</p>

      <!-- À SURVEILLER -->
      <h2 style="color:#1e3a5f;border-bottom:2px solid #dbeafe;padding-bottom:8px;margin-top:28px">⏰ À Surveiller Aujourd'hui</h2>
      <ul style="padding-left:20px">{surveiller_html}</ul>

    </div>

    <!-- FOOTER -->
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

# ─── SAUVEGARDE POUR GITHUB PAGES ─────────────────────────────────────────────
os.makedirs("docs/editions", exist_ok=True)

# Page de l'édition du jour
with open(f"docs/editions/{today_iso}.html", "w", encoding="utf-8") as f:
    f.write(html_content)

# Mise à jour de l'index
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
