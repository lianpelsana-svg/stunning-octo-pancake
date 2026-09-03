import os
import re
import csv
import asyncio
import requests
import discord
from discord.ext import commands

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
        
    def get_winning_keyword(self, seed_keyword):
        url = f"https://http2.mlstatic.com/resources/sites/{self.site_id}/autosuggest?q={seed_keyword}"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            suggestions = response.json().get("suggested_queries", [])
            return suggestions[0].get("q") if suggestions else seed_keyword
        except Exception:
            return seed_keyword

    def get_top_keywords(self, seed_keyword, limit=8):
        url = f"https://http2.mlstatic.com/resources/sites/{self.site_id}/autosuggest?q={seed_keyword}"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            suggestions = response.json().get("suggested_queries", [])
            keywords = [item.get("q") for item in suggestions[:limit]]
            return keywords if keywords else [seed_keyword]
        except Exception:
            return [seed_keyword]

    def analyze_market(self, keyword, limit=15):
        try:
            response = requests.get(self.search_url, params={"q": keyword, "limit": limit})
            results = response.json().get("results", [])
        except Exception as e:
            return {"error": str(e)}

        report = {"keyword": keyword, "total_analyzed": len(results), "items": []}
        for item in results:
            brand = next((a.get("value_name", "") for a in item.get("attributes", []) if a.get("id") == "BRAND"), "")
            validator = MercadoLibreSEOValidator(item.get("title", ""), brand=brand)
            report["items"].append({
                "id": item.get("id"), "price": item.get("price"),
                "seo": validator.validate(), "link": item.get("permalink")
            })
        return report

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
        winning_kw = await asyncio.to_thread(agent.get_winning_keyword, keyword)
        market_data = await asyncio.to_thread(agent.analyze_market, winning_kw, limit=15)
        
        if "error" in market_data:
            await wait_msg.edit(content=f"❌ Error al consultar la API: {market_data['error']}")
            return

        # Respaldo automático si la sugerencia no arroja productos
        if not market_data.get("items"):
            winning_kw = keyword
            market_data = await asyncio.to_thread(agent.analyze_market, winning_kw, limit=15)
            if not market_data.get("items"):
                await wait_msg.edit(content=f"⚠️ MercadoLibre no devolvió productos para '**{keyword}**'. Prueba con otra palabra clave.")
                return

        safe_kw = "".join(c for c in winning_kw if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
        filename = f"reporte_{safe_kw}.csv"
        
        await asyncio.to_thread(agent.export_csv, market_data, filename)

        total_items = len(market_data["items"])
        aprobados = sum(1 for item in market_data["items"] if item["seo"]["is_valid"])
        
        embed = discord.Embed(title="📊 Auditoría SEO Mercado Libre", color=discord.Color.green())
        embed.add_field(name="Keyword Semilla", value=f"*{keyword}*", inline=True)
        embed.add_field(name="Keyword Ganadora", value=f"**{winning_kw}**", inline=True)
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
    wait_msg = await ctx.send(f"🔍 Buscando tendencias de búsqueda para: **{keyword}**...")
    try:
        agent = MeliMasterSEOAgent(site_id="MLA")
        top_kws = await asyncio.to_thread(agent.get_top_keywords, keyword, limit=8)
        
        embed = discord.Embed(
            title="🔥 Tendencias de Búsqueda en Mercado Libre",
            description=f"Términos más populares basados en lo que la gente busca para: *{keyword}*",
            color=discord.Color.blue()
        )
        
        lista_format = ""
        for i, kw in enumerate(top_kws, 1):
            lista_format += f"**{i}.** `{kw}`\n"
            
        embed.add_field(name="Palabras Clave Sugeridas", value=lista_format, inline=False)
        embed.set_footer(text="Usa estas keywords en tus títulos para ganar visibilidad.")
        
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
    
