# The Unofficial Guide — Project 1

---

## Domain

US based Immigration Guide. Official channels are only meant to provide a broader guidance on immigration rules and procedures. Official channels can also be slow to respond to queries or are not easy to reach out to.

---

## Document Sources

| # | Source | Description | URL or location |
|---|--------|-------------|-----------------|
| 1 | Reddit| Subreddit of USCIS(U.S. Citizenship and Immigration Services), a federal agency overseeing lawful immigration, processes citizenship, naturalization applications etc. | https://www.reddit.com/r/USCIS/ | 
| 2 | Reddit| Subreddit that answers US Based and worldwide immigration | https://www.reddit.com/r/immigration/ | 
| 3 | Reddit| Subreddit that has news, questions, FAQs etc about H1B working visas | https://www.reddit.com/r/h1b/ | 
| 4 | Reddit| Subreddit that has news, questions, FAQs etc about F1 student visas | https://www.reddit.com/r/f1visa/ | 
| 5 | Reddit| Subreddit that has news, questions, FAQs etc about Green Cards for permanent residency| https://www.reddit.com/r/greencard/ | 
| 6 | Reddit | A Subreddit for DREAMers under Deferred Action for Childhood Arrivals (DACA) |https://www.reddit.com/r/daca/| 
| 7 | Website| FAQ section that answers questions about the latest and general US based immigration processes |https://www.murthy.com/view-all-faq/ |  
| 8 | Website| Blog that talks about latest and general US based immigration processes| https://www.ashoorilaw.com/blog/| 
| 9 | Website| Blog that talks about latest and general US based immigration processes | https://eaganimmigration.com/blog/ | 
| 10 | Website | Blog that answers basics questions about US Based immigrations |https://www.boundless.com/blog/top-us-work-visa-faqs-reddit |
---

## Chunking Strategy

**Chunk size:**

For FAQs, chunk each FAQ itself. 200 tokens
For Reddit, form post title and each comment as a chunk, and also post title and body as another chunk to provide additional information not present in the title during Retrieval.
If there are replies to the comment, only then apply token limits. Start with 200 tokens
For Blogs, chunk by paragraph first. If it's larger than 200 tokens, then split further. 


**Overlap:**

Keep 0 overlap for FAQs and Reddit.
Keep an overlap of 75 tokens for Blogs.

**Why these choices fit your documents:**

FAQs and Reddit have a natural QnA format which makes it easy for accurate retrieval when chunked together. Looking at the FAQs, they seemed to be under 200-300 words. Overlapping is not needed as each chunk already has the full context. 

One thing I observed is that Reddit has a nested and complicated structure of comments and replies. To simplify things and avoid the chunks from becoming too large and irrelevant due to replies, I decided to split the chunk further if it exceeds 200 tokens. 

Blogs on the other hand have a structured format with headings, paragraphs etc. These require larger chunks and overlap to retain continuation for more detailed queries. It seemed tempting to increase to 500-800 tokens, but thus caused the chunks to have too much information about a lot of topics. Upon looking at the blog sources, each paragraph has a lot of information on its own so that I decided overlapping would be better.

**Final chunk count:**

86219

**Sample chunks**

Link to [five sample chunks](documents/sample_chunks.txt), along with source names. 

---

## Embedding Model

**Model used:**
all-MiniLM-L6-v2

**Production tradeoff reflection:**

Support for Spanish, Chinese, Hindi based documents.
Different embeddng model that can reflect immigration language and dictionary.
Benchmarking different models local and hosted to check latency and other NLP related parameters.

**Retrieval Approach**

Semantic search, BM25 keyword and hybrid search combining the both. The Hybrid apporach uses Rank Reciprocal Fusion to provide a centralized score and equal weight for both. This works by
taking the reciprocal of the distance and bm25 scores which also have a constant factor added to them to prevent extreme values from affecting the final rank.

Use metadata filtering on queries as well. Display distance score, chunks retrieved, metadata included for K=5.

**Sample Retrievals**

For details on metrics and runs, refer to [Sample Retrievals and Metrics](responses/retrieval_tests.txt). 

Summary:

The tests on the 3 queries were done with all the methods above and based on the results semantic search worked the best. BM25 did not work as well as semantic search, hence hybrid search didn't as well. My hypothesis is that BM25 could work well if there are very specific keywords or jargon that one is looking for. The nature of the queries are such that there are a lot of filler keywords and non specific words that can match unrelated sources, especially for a Reddit corpus as large as what was scrapped here. 

For all three queries, the distance scores were under 0.5

For for the query `How do I know if I will be eligible for H1B lottery in 2026 under Masters degree quota in STEM?`: The distance score is 0.3, and the chunks mostly talk about H1B lottery eligibility, interestingly the chunks come from r/f1visa as it seems like this question comes up more frequently for folks with an F1 visa as they enter the lottery.

The distance scores however were were higher for `How long does premium processing take for J1 visas and how much does it cost?`, around 0.4 and the chunks reflect this as they talk about premium processing for other visa types but not J1.

---

## Grounded Generation

**System prompt grounding instruction:**

     You are The Unofficial Immigration Guide, an assistant that answers questions about US \
     immigration using ONLY the context sources provided by the user.

     Rules:
     - Base every claim strictly on the context sources. Do not use outside knowledge.
     - Cite the sources you used inline with bracketed numbers, e.g. [1], [2]. 
     - If the context does not contain enough information to answer, say so plainly \
     and do not guess. Do not fabricate citations.
     - If the question is outside US immigration or unrelated to the context, say it \
     is outside the scope of this guide. Do not cite any sources.
     - The context is drawn from forums and community posts (Reddit, FAQs, blogs), \
     so it may be anecdotal — note when guidance reflects user experience rather \
     than official rules, and remind the user to verify with official USCIS sources \
     for anything time-sensitive.
     - Be concise and direct. Answer in plain language.\

    For cases with no relevant chunks retrieved:
     "I couldn't find anything relevant in the guide.
     "Try rephrasing your question."

**How source attribution is surfaced in the response:**

Source attribution is ensured through code rather than the LLM to provide a consistent format.
However this causes an issue where any query that is out of scope will have its sources cited.
(Due to lack of time, I was unable to test the prompt inserting sources)

---

## Evaluation Report

**How to generate responses**

1. Fork or clone the repository.
2. Navigate to the file generator.py and search for `test_generator`. It will loop through a set of questions defined in a list called `EVAL_QUESTIONS` located in `retriever.py`. That is the input provided to the model.
3. Run `python generator.py` on your CLI. It will generate responses which cites the sources it uses.

Below are the questions tested against the system:


| # | Question | Expected answer | System response (summarized) | Retrieval quality | Response accuracy |
|---|----------|-----------------|------------------------------|-------------------|-------------------|
| 1 | What documents do I need for a greencard application if I am married to a us citizen but I live outside of the US? | If you live outside the U.S. and are married to a U.S. citizen, you must use Consular Processing. This requires filing ⁠Form I-130 and applying for an immigrant visa through the ⁠DS-260. You will need civil documents, financial evidence, proof of a genuine marriage, and medical/police records|[ Link](/responses/evaluation_query_response_1) | Relevant| Accurate |
| 2 | How long does premium processing take for J1 visas and how much does it cost?| Premium processing for J-1 visa applicants changing or extending their nonimmigrant status within the U.S. takes 30 calendar days and costs \(\$2,075\). This expedited service is requested using ⁠Form I-907, Request for Premium Processing Service alongside Form I-539, Application to Extend/Change Nonimmigrant Status | [Link](/responses/evaluation_query_response_2) | Partially relevant |  Partially accurate|
| 3 | How do I know if I will be eligible for H1B lottery in 2026 under Masters degree quota in STEM?| USCIS has shifted to a wage-based selection system which can directly impact your odds. If your employer offers a role that aligns with a higher Department of Labor (DOL) prevailing wage level (Level III or Level IV) and you hold a U.S. Master's degree, your registration can receive compounded entries, heavily favoring your selection in the lottery before going to the Master's cap pool | [Link](/responses/evaluation_query_response_3) |Partially Relevant | Partially Accurate |
| 4 | I did not receive my EAD card I applied for under H4 visa. USCIS portal shows that it's mailed. What do I do?| Find the tracking number in your USCIS Account under your H-4 EAD case status.If it says Delivered, check your mailroom, front desk, or neighbors. If still missing, immediately contact your local post office to request a Missing Mail Search. If it says Undeliverable/Returned to Sender, the card is likely heading back to USCIS.  Wait at least 7 business days (but no more than 90 days) after the mailing date before contacting them. Submit a Non-Delivery of Card request using the erequest tool. | [Link](/responses/evaluation_query_response_4)| Relevant| Accurate |
| 5 | I got rejected in my F1 Visa application and I have classes coming up in a month? How do I reapply with this in mind?| With classes starting in a month, you can reapply immediately, but you must first address the reason for your denial. To salvage your upcoming semester, you need to fix any application flaws, secure a new I-20 with an updated start date, and request an expedited interview. | [Link](/responses/evaluation_query_response_5) | Relevant | Accurate |
| 6 | (Out of scope) How do I apply for Schengen Visa? | (Systems says it cannot give any information as it's not related to US immigration) |[Link](/responses/evaluation_query_response_6)  | Off-target | Accurate |
| 7 | (Out of scope)What is the weather? |(Systems says it cannot give any information as it's not related to US immigration) |[Link](/responses/evaluation_query_response_7)  | Relevant | Accurate |

**Retrieval quality:** Relevant / Partially relevant / Off-target  
**Response accuracy:** Accurate / Partially accurate / Inaccurate

---

## Failure Case Analysis

**Question that failed:**

Q1.How long does premium processing take for J1 visas and how much does it cost?
Q3.How do I know if I will be eligible for H1B lottery in 2026 under Masters degree quota in STEM?
Q6.How do I apply for Schengen Visa?

**What the system returned:**

A1:[Link](/responses/evaluation_query_response_1)

A3:[Link](/responses/evaluation_query_response_3)

A6:[Link](/responses/evaluation_query_response_6)

**Root cause (tied to a specific pipeline stage):**

Q1.The actual data about premium processing was available, but for J1 visa it was unable to find any specific information because there were less references to it.

Q3: The souurces refer to the latest changes in the H1B based lottery cited, but at the Generation stage the model missed using that piece of information.

Q6. Some of the information about non US immigration slipped through in the Ingestion Pipeline, despite filters to catch any non US data. In this instance, the model though the prompt identified it and was able to provide a grounded response.

**What you would change to fix it:**

I would like to rebalance the datasets collected and improve filters to prevent irrelevant information from showing up. 
(Reddit alone has around ~8000 posts and 20,000 comments compared to Blogs and FAQs that were under 200 documents!)
I also would dig into why the model failed to use the relevant chunks to cite an answer. My guess is that it has something to do with the temperature settings, but I did not get a chance to explore.

---


## Spec Reflection

**One way the spec helped you during implementation:**
It helped me to debug and understand what each stage of the RAG pipeline should look like, which saved hours of figuring that out. E.g inspecting the chunks, retrieval metrics etc.

**One way your implementation diverged from the spec, and why:**

In my implementation, I asked Claude Code to help me outline the skeletal code of each stage so that I could get a better picture of the whole flow, otherwise it felt like a black box for me.
Additionally I iterated through the data collection, chunking and ingestion stages multiple times as some of the initial datasets collected were tedious or impossible to scrap and it helped me to scope down my data.

---

## AI Usage

**Instance 1**

- *What I gave the AI:*
Documents collected under `documents`, `Document sources` and `Chunking` in `planning.md` for loading Reddit Data from Arctic Shift(API that gets historical data through periodic dumps).
- *What it produced:*
It produced `ingest.py`, `parse_html.py` and `chunking.py`, which 
- *What I changed or overrode:*
For `ingest.py` I noticed rate limit issues and lots of time taken to load posts and comments. 

I asked it to add rate limits in `get_comments()` and also use Thread executors for loading posts in `scrape_immigration_posts`. I also tried concurrency for `get_comments` but the server was getting rate limited very quickly so I modifed the number of workers from 16 that was generated to 5 to reduce some of the issues.

For `chunking.py`, I modified the token counts from 100 to 200 after checking some chunks. Also I asked Claude Code to remove deleted or redacted posts and comments for Reddit data along with ensuring it had a score > 1 to remove as much noise as possible.

**Instance 2**

- *What I gave the AI:*
`Retrieval Approach` from `planning.md` along with `chunking.py` to produce the Retrieval and Generation code.
- *What it produced:*
`retriever.py`, `embeddings.py`, `generator.py`, `app.py`
- *What I changed or overrode:*
In `embeddings.py`, I changed the batch size to be the maximum batch size: 5461 to speed up the index building process.

In `retriever.py`, Claude Code generated results for the hybrid retrieval only. I modified the `test_retriever` function to add both bm25 keyword search and semantic search.

