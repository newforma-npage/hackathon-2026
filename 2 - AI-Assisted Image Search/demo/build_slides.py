"""Generate the demo slide deck as a .pptx file."""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)

# Colors
DARK_BG = RGBColor(0x1A, 0x1A, 0x2E)
ACCENT = RGBColor(0x00, 0xD4, 0xAA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_GRAY = RGBColor(0xCC, 0xCC, 0xCC)
ORANGE = RGBColor(0xFF, 0x8C, 0x00)


def add_dark_bg(slide):
    """Fill slide background with dark color."""
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = DARK_BG


def add_text_box(slide, left, top, width, height, text, font_size=18,
                 bold=False, color=WHITE, alignment=PP_ALIGN.LEFT):
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.bold = bold
    p.font.color.rgb = color
    p.alignment = alignment
    return tf


def add_bullet_slide(slide, bullets, start_top=Inches(2.0), color=LIGHT_GRAY, size=20):
    txBox = slide.shapes.add_textbox(Inches(1), start_top, Inches(11), Inches(4.5))
    tf = txBox.text_frame
    tf.word_wrap = True
    for i, bullet in enumerate(bullets):
        if i == 0:
            p = tf.paragraphs[0]
        else:
            p = tf.add_paragraph()
        p.text = bullet
        p.font.size = Pt(size)
        p.font.color.rgb = color
        p.space_after = Pt(12)


# ═══════════════════════════════════════════════════════════════════
# SLIDE 1: Title
# ═══════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank
add_dark_bg(slide)
add_text_box(slide, Inches(1), Inches(2), Inches(11), Inches(1.5),
             "Visual Project Intelligence Search",
             font_size=44, bold=True, color=ACCENT, alignment=PP_ALIGN.CENTER)
add_text_box(slide, Inches(1), Inches(3.5), Inches(11), Inches(1),
             "AI-Powered Image Search for Construction Projects",
             font_size=24, color=WHITE, alignment=PP_ALIGN.CENTER)
add_text_box(slide, Inches(1), Inches(5.5), Inches(11), Inches(1),
             "P4: Vector Store & Schema  |  AWS OpenSearch Serverless + Bedrock Titan",
             font_size=16, color=LIGHT_GRAY, alignment=PP_ALIGN.CENTER)

# ═══════════════════════════════════════════════════════════════════
# SLIDE 2: The Problem
# ═══════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_text_box(slide, Inches(1), Inches(0.5), Inches(11), Inches(1),
             "The Problem", font_size=36, bold=True, color=ACCENT)
add_bullet_slide(slide, [
    "• Project teams store thousands of images",
    "• No way to search by visual content",
    "• Current approach: browse filenames or scroll through folders",
    "• Finding the right photo takes 15–30 minutes",
    "",
    '  "Where\'s that photo of the crack on Pier P-3?"',
], start_top=Inches(1.8))

# ═══════════════════════════════════════════════════════════════════
# SLIDE 3: The Solution
# ═══════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_text_box(slide, Inches(1), Inches(0.5), Inches(11), Inches(1),
             "The Solution", font_size=36, bold=True, color=ACCENT)
add_bullet_slide(slide, [
    "AI-powered image search using natural language",
    "",
    "How it works:",
    "  1. Image → Bedrock Titan Multimodal → 1536-dim embedding",
    "  2. Embedding stored in OpenSearch Serverless (vector search)",
    "  3. Query text → same model → cosine similarity → ranked results",
    "",
    'User types: "concrete crack damage"',
    "System returns: ranked photos matching that description",
], start_top=Inches(1.8))

# ═══════════════════════════════════════════════════════════════════
# SLIDE 4: Demo Flow
# ═══════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_text_box(slide, Inches(1), Inches(0.5), Inches(11), Inches(1),
             "Live Demo — 3 Minutes", font_size=36, bold=True, color=ACCENT)
add_bullet_slide(slide, [
    "STEP 1 — INGEST",
    "  Index 5 site photos with AI-generated embeddings",
    "",
    "STEP 2 — NATURAL LANGUAGE SEARCH",
    '  Query: "concrete crack damage" → top 3 results',
    "",
    "STEP 3 — FILTER BY PROJECT",
    "  Same query, restricted to PROJ-001 only",
    "",
    "STEP 4 — SIMILAR IMAGE",
    "  Upload a photo → find visually similar images across projects",
], start_top=Inches(1.8), size=18)

# ═══════════════════════════════════════════════════════════════════
# SLIDE 5: Architecture
# ═══════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_text_box(slide, Inches(1), Inches(0.5), Inches(11), Inches(1),
             "Architecture — P4 Scope", font_size=36, bold=True, color=ACCENT)

# Architecture diagram as text
arch_text = (
    "┌─────────────┐      ┌────────────────────┐      ┌─────────────┐\n"
    "│  Dev 3       │      │  P4 (This Sprint)  │      │  Dev 5      │\n"
    "│  Bedrock     │─────▶│  VectorStore Module │◀─────│  Search API │\n"
    "│  Embeddings  │      │  + OpenSearch Index │      │  Endpoint   │\n"
    "└─────────────┘      └────────────────────┘      └─────────────┘\n"
    "                              │\n"
    "                              ▼\n"
    "                   ┌────────────────────────┐\n"
    "                   │  OpenSearch Serverless  │\n"
    "                   │  Collection: image-search │\n"
    "                   └────────────────────────┘"
)
txBox = slide.shapes.add_textbox(Inches(0.5), Inches(1.8), Inches(12), Inches(3.5))
tf = txBox.text_frame
tf.word_wrap = False
p = tf.paragraphs[0]
p.text = arch_text
p.font.size = Pt(12)
p.font.color.rgb = WHITE
p.font.name = "Consolas"

# Schema table as text
schema = (
    "Index Schema:\n"
    "  image_id    keyword        Unique ID (doc _id)\n"
    "  project_id  keyword        Filter by project\n"
    "  embedding   knn_vector     1536-dim, cosine, FAISS HNSW\n"
    "  tags        keyword[]      AI-generated labels\n"
    "  date        date           Time filtering\n"
    "  location    keyword        Spatial context"
)
add_text_box(slide, Inches(1), Inches(5.0), Inches(11), Inches(2.5),
             schema, font_size=14, color=LIGHT_GRAY)

# ═══════════════════════════════════════════════════════════════════
# SLIDE 6: What We Built
# ═══════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_text_box(slide, Inches(1), Inches(0.5), Inches(11), Inches(1),
             "What We Built (P4)", font_size=36, bold=True, color=ACCENT)
add_bullet_slide(slide, [
    "✅  CDK Stack — one-command deploy (cdk deploy)",
    "     OpenSearch Serverless + encryption/network/access policies",
    "",
    "✅  Index Creation Script — idempotent, SigV4 auth",
    "",
    "✅  VectorStore Client — clean Python API",
    "     index_image() | search_by_embedding() | delete_image()",
    "",
    "✅  Full Test Suite — 30 tests passing",
    "     Unit + Property-Based (Hypothesis) + CDK Snapshot",
    "",
    "✅  README + Handoff Docs — ready for Dev 3 & Dev 5",
], start_top=Inches(1.8), size=18)

# ═══════════════════════════════════════════════════════════════════
# SLIDE 7: KPIs
# ═══════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_text_box(slide, Inches(1), Inches(0.5), Inches(11), Inches(1),
             "KPIs & Impact", font_size=36, bold=True, color=ACCENT)
add_bullet_slide(slide, [
    "📉  Time to locate images:        ↓ 60%",
    "     Natural language vs filename browsing",
    "",
    "📈  Image reuse across projects:   ↑ 25%",
    "     Similar image search surfaces existing photos",
    "",
    "🎯  Search success (first attempt): ↑ 40%",
    "     AI understands intent, not just keywords",
], start_top=Inches(2.0), size=22)

# ═══════════════════════════════════════════════════════════════════
# SLIDE 8: Next Steps
# ═══════════════════════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_dark_bg(slide)
add_text_box(slide, Inches(1), Inches(0.5), Inches(11), Inches(1),
             "Next Steps", font_size=36, bold=True, color=ACCENT)
add_bullet_slide(slide, [
    "1.  Dev 3 — Connect Bedrock Titan Multimodal for real embeddings",
    "",
    "2.  Dev 5 — Build REST API endpoint for frontend",
    "",
    "3.  Frontend — Search bar + image grid UI",
    "",
    "4.  Scale — Auto-tagging pipeline for bulk ingestion",
    "",
    "",
    "Thank you!",
], start_top=Inches(1.8), size=22)


# ═══════════════════════════════════════════════════════════════════
# SAVE
# ═══════════════════════════════════════════════════════════════════
output_path = r"d:\Hackathon\2 - AI-Assisted Image Search\demo\Demo_Slides.pptx"
prs.save(output_path)
print(f"✓ Slides saved to: {output_path}")
