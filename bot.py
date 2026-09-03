import os
import re
import csv
import asyncio
import requests
import discord
from discord.ext import commands
from collections import Counter

# ==========================================
# VALIDADOR Y AGENTE SEO DE MERCADO LIBRE
# ==========================================
class MercadoLibreSEOValidator:
    def __init__(self, title, brand=""):
        self.title = title.strip()
        self.brand = brand.lower()
        self.results = {"score": 100, "title": self.title, "warnings": [], "errors": [], "is_valid": True}

    def validate(self):
        length = len(self.title)
        if length > 60:
            self.results["errors"].append("Supera 60 caracteres (truncamiento).")
            self.results["score"] -= 20
        elif length < 30:
            self.results["warnings"].append("Muy corto, desperdicia espacio.")
            self.results["score"] -= 10
        if self.title.isupper():
            self.results["errors"].append("Mayúsculas cerradas.")
            self.results["score"] -= 15
        if re.search(r'[%$!@#*?]|oferta|gratis|envío', self.title, re.IGNORECASE):
            self.results["errors"].append("Contiene spam promocional.")
            self.results["score"] -= 15
        if self.brand and self.brand not in self.title.lower():
            self.results["warnings"].append("La marca no está presente.")
            self.results["score"] -= 10
        if self.results["score"] < 70:
            self.results["is_valid"] = False
        return self.results

class MeliMasterSEOAgent:
    def __init__(self, site_id="MLA"):
        self.site_id = site_id
        self.search_url = f"https://api.mercadolibre.com/sites/{site_id}/search"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://www.mercadolibre.com.ar/"
        }

    def analyze_market(self, keyword, limit=20):
        try:
            response = requests.get(self.search_url, headers=self.headers, params={"q": keyword, "limit": limit}, timeout=5)
            results = response.json().get("results", [])
        except Exception as e:
            return {"error": str(e)}

        report = {"keyword": keyword, "total_analyzed": len(results), "items": []}
        for item in results:
            brand = next((a.get("value_name", "") for a in item.get("attributes", []) if a.get("id") == "BRAND"), "")
            validator = MercadoLibreSEOValidator(item.get("title", ""), brand=brand)
            report["items"].append({
                "id": item.get("id"), "price": item.get("price"), "title": item.get("title"),
                "seo": validator.validate(), "link": item.get("permalink")
            })
        return report

    def extract_top_keywords(self, market_data, limit=8):
        # Stopwords comunes en español para ignorar palabras vacías
        stopwords = {"de", "la", "el", "en", "y", "a", "los", "del", "se", "las", "por", "un", "para", "con", "no", "una", "su", "al", "lo", "como", "más", "pero", "sus", "le", "ya", "o", "fue", "este", "ha", "sí", "porque", "esta", "son", "entre", "está", "cuando", "muy", "sin", "sobre", "ser", "tiene", "también", "me", "hasta", "hay", "donde", "han", "quien", "están", "estado", "desde", "todo", "nos", "durante", "estados", "todos", "uno", "les", "ni", "contra", "otros", "fueron", "ese", "eso", "había", "ante", "ellos", "e", "esto", "mí", "antes", "algunos", "qué", "unos", "yo", "otro", "otras", "otra", "él", "tanto", "esa", "estos", "ulc", "pulgadas", "ml", "cm"}
        
        words = []
        for item in market_data.get("items", []):
            title = item.get("title", "").lower()
            # Limpiamos caracteres especiales y separamos palabras
            clean_words = re.findall(r'\b[a-záéíóúñ]{3,}\b', title)
            for w in clean_words:
                if w not in stopwords:
                    words.append(w)
                    
        # Contamos pares de palabras (bigramas) o palabras sueltas más repetidas
        counter = Counter(words)
        common_words = [word.capitalize() for word, freq in counter.most_common(limit)]
        return common_words if common_words else [market_data.get("keyword")]

    def export_csv(self, report, filename="seo_market_analysis.csv"):
        items = report.get("items", [])
        if not items: return
        headers = ["ID", "Precio", "Puntaje_SEO", "Estado", "Titulo", "Errores_SEO", "Link"]
        with open(filename, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for item in items:
                seo = item["seo"]
                writer.writerow([
                    item["id"], item["price"], seo["score"],
                    "Aprobado" if seo["is_valid"] else "Revisar", seo["title"],
                    " | ".join(seo["errors"] + seo["warnings"]) if (seo["errors"] or seo["warnings"]) else "Perfecto",
                    item["link"]
                ])

# ==========================================
# CONFIGURACIÓN DEL BOT DE DISCORD
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, case_insensitive=True)

@bot.event
async def on_ready():
    print(f'🔥 Bot conectado exitosamente como {bot.user}')

@bot.command(name='seo')
async def seo_analysis(ctx, *, keyword: str):
    wait_msg = await ctx.send(f"🔍 Analizando el mercado para: **{keyword}**... Un momento.")
    filename = None
    try:
        agent = MeliMasterSEOAgent(site_id="MLA")
        market_data = await asyncio.to_thread(agent.analyze_market, keyword, limit=20)
        
        if "error" in market_data:
            await wait_msg.edit(content=f"❌ Error al consultar la API: {market_data['error']}")
            return

        if not market_data.get("items"):
            await wait_msg.edit(content=f"⚠️ MercadoLibre no devolvió productos para '**{keyword}**'. Prueba con otra palabra clave.")
            return

        safe_kw = "".join(c for c in keyword if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
        filename = f"reporte_{safe_kw}.csv"
        
        await asyncio.to_thread(agent.export_csv, market_data, filename)

        total_items = len(market_data["items"])
        aprobados = sum(1 for item in market_data["items"] if item["seo"]["is_valid"])
        
        embed = discord.Embed(title="📊 Auditoría SEO Mercado Libre", color=discord.Color.green())
        embed.add_field(name="Keyword Analizada", value=f"**{keyword}**", inline=True)
        embed.add_field(name="Aprobados", value=f"{aprobados}/{total_items}", inline=False)
        
        if os.path.exists(filename):
            with open(filename, 'rb') as f:
                await ctx.send(embed=embed, file=discord.File(f, filename=filename))
            os.remove(filename)
            
        await wait_msg.delete()
    except Exception as e:
        await wait_msg.edit(content=f"❌ Ocurrió un error: {str(e)}")
    finally:
        if filename and os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

@bot.command(name='keywords', aliases=['kw'])
async def keyword_research(ctx, *, keyword: str):
    wait_msg = await ctx.send(f"🔍 Extrayendo palabras clave de los mejores productos para: **{keyword}**...")
    try:
        agent = MeliMasterSEOAgent(site_id="MLA")
        market_data = await asyncio.to_thread(agent.analyze_market, keyword, limit=20)
        
        if "error" in market_data or not market_data.get("items"):
            await wait_msg.edit(content=f"❌ No se pudieron obtener datos para '**{keyword}**'.")
            return

        top_kws = agent.extract_top_keywords(market_data, limit=8)
        
        embed = discord.Embed(
            title="🔥 Palabras Clave Dominantes del Mercado",
            description=f"Términos más repetidos en los títulos de los principales competidores para: *{keyword}*",
            color=discord.Color.blue()
        )
        
        lista_format = ""
        for i, kw in enumerate(top_kws, 1):
            lista_format += f"**{i}.** `{kw}`\n"
            
        embed.add_field(name="Palabras Clave Extraídas", value=lista_format, inline=False)
        embed.set_footer(text="Usa estos términos para optimizar tu título en Mercado Libre.")
        
        await ctx.send(embed=embed)
        await wait_msg.delete()
    except Exception as e:
        await wait_msg.edit(content=f"❌ Ocurrió un error: {str(e)}")

if __name__ == "__main__":
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("❌ ERROR: Falta la variable DISCORD_TOKEN")
    else:
        bot.run(token)
        
