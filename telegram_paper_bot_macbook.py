import os
import time
import threading
import schedule
from datetime import datetime
import pytz
from Bio import Entrez
import arxiv
from transformers import pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import telebot
from telebot.types import Message



# --- CONFIGURATION ---
TOKEN = "7676094696:AAEQa70ooBDFCGkIil-vjq2cekUksM8LxLs"
Entrez.email = "041198andrey@mail.ru"
CHAT_ID = "1982953374"  # Keep as string for easier comparison
KEYWORDS = ["machine learning", "scRNA-seq", "genomics", "deep learning", "single cell transcriptomics"]

# Initialize bot
bot = telebot.TeleBot(TOKEN)

# --- NLP MODEL FOR SUMMARIZATION ---
summarizer = pipeline("summarization", model="facebook/bart-large-cnn")

# --- TRACK SHOWN PAPERS ---
shown_papers = set()

# --- Message Handlers ---
@bot.message_handler(commands=['start'])
def send_welcome(message: Message):
    bot.reply_to(message, "📚 Hi! I'm your research paper bot. I send daily papers and echo messages.")

@bot.message_handler(func=lambda msg: True)
def echo_all(message: Message):
    if str(message.chat.id) == CHAT_ID:
        bot.reply_to(message, f"🔁 You said: {message.text}")



def add_shown_papers(papers):
    for paper in papers:
        shown_papers.add(paper['url'])

def is_paper_shown(paper):
    return paper['url'] in shown_papers

def filter_new_papers(papers):
    return [paper for paper in papers if not is_paper_shown(paper)]

# --- FETCHERS ---
def fetch_pubmed(keywords):
    try:
        query = " OR ".join(keywords)
        handle = Entrez.esearch(db="pubmed", term=query, retmax=20, sort="relevance")
        ids = Entrez.read(handle)["IdList"]
        handle.close()
        handle = Entrez.efetch(db="pubmed", id=",".join(ids), retmode="xml")
        records = Entrez.read(handle)
        handle.close()
        return [
            {
                "title": art["MedlineCitation"]["Article"]["ArticleTitle"],
                "abstract": art["MedlineCitation"]["Article"].get("Abstract", {}).get("AbstractText", [""])[0],
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{art_id}/",


            }
            for art, art_id in zip(records["PubmedArticle"], ids)
        ]
    except Exception as e:
        print(f"Error fetching PubMed articles: {e}")
        return []

def fetch_arxiv(keywords):
    try:
        client = arxiv.Client()
        search = arxiv.Search(
            query=" OR ".join(keywords),
            max_results=20,
            sort_by=arxiv.SortCriterion.SubmittedDate
        )
        results = client.results(search) 
        return [{
            "title": r.title,
            "abstract": r.summary,
            "url": r.entry_id,
            "published": r.published.date()
        } for r in results]
    except Exception as e:
        print(f"Error fetching arXiv: {e}")
        return []

# --- UTILS ---
def rank_papers(papers, keywords):
    # Use TF-IDF to rank papers based on relevance to keywords
    abstracts = [paper["abstract"] for paper in papers]
    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(abstracts + [" ".join(keywords)])
    relevance_scores = cosine_similarity(tfidf_matrix[-1], tfidf_matrix[:-1]).flatten()
    ranked_papers = sorted(zip(papers, relevance_scores), key=lambda x: x[1], reverse=True)
    return [paper for paper, score in ranked_papers]

def format_paper(paper):
    return f"• <b>{paper['title']}</b>\n{paper['url']}"

def fetch_and_filter_papers(keywords):
    papers = fetch_pubmed(keywords) + fetch_arxiv(keywords)
    ranked_papers = rank_papers(papers, keywords)
    return ranked_papers

# --- SCHEDULER ---
def send_daily_papers():
    papers = fetch_and_filter_papers(KEYWORDS)
    new_papers = filter_new_papers(papers)
    
    if not new_papers:
        bot.send_message(CHAT_ID, "📭 No new papers today.")
        return

    # Split into top 5 and the rest
    top_papers = new_papers[:5]
    other_papers = new_papers[5:]

    # Format top papers
    message = "📚 *Top 5 Papers Today:*\n\n" + "\n\n".join(
        f"• [{p['title']}]({p['url']})\n📅 {p.get('published', 'N/A')}"
        for p in top_papers
    )

    # Add "Show More" if there are additional papers
    if other_papers:
        summaries = summarizer(
            " ".join([p["abstract"] for p in other_papers]),
            max_length=150,
            min_length=30,
            do_sample=False
        )[0]["summary_text"]
        
        message += (
            f"\n\n🔍 *{len(other_papers)} More Papers Summary:*\n"
            f"{summaries}\n"
        )

    bot.send_message(
        CHAT_ID,
        message,
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    add_shown_papers(new_papers)

def run_scheduler():
    moscow_tz = pytz.timezone("Europe/Moscow")
    schedule.every().day.at("09:00", moscow_tz).do(send_daily_papers)
    # For testing, run immediately:
    #schedule.every(1).minutes.do(send_daily_papers)
    
    while True:
        schedule.run_pending()
        time.sleep(1)

def main():
    try:
        print("🤖 Starting bot...")
        
        # Start scheduler
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()

        # Start bot
        updater = Updater(TOKEN, use_context=True)
        dp = updater.dispatcher
        
        dp.add_handler(CommandHandler("start", start))
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, echo))
        
        print("🔄 Bot is polling for messages...")
        updater.start_polling()
        updater.idle()

    except Exception as e:
        print(f"🚨 Error: {e}")
    finally:
        print("Bot stopped.")


# --- Start Bot & Scheduler ---
if __name__ == "__main__":
    print("🤖 Bot starting...")
    
    # Start scheduler in background thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    # Start bot polling
    print("🔄 Bot is now polling for messages...")
    bot.infinity_polling()