"""Generate PDF from the presentation markdown using fpdf2 with proper spacing."""
import re
from fpdf import FPDF

MD_PATH = "superpowers/specs/2026-04-04-project-presentation-design.md"
PDF_PATH = "../reference/Code_Knowledge_Graph_Presentation.pdf"

with open(MD_PATH, encoding="utf-8") as f:
    md_text = f.read()

# Colors
DARK = (13, 33, 55)
BLUE = (26, 82, 118)
BLACK = (30, 30, 30)

# Indentation for bullet content (bullet char + text)
BULLET_INDENT = 10
BULLET_TEXT_INDENT = 15  # where text starts (after bullet char)


class PDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("Segoe", "", "C:/Windows/Fonts/segoeui.ttf")
        self.add_font("Segoe", "B", "C:/Windows/Fonts/segoeuib.ttf")
        self.add_font("Segoe", "I", "C:/Windows/Fonts/segoeuii.ttf")
        self.add_font("Segoe", "BI", "C:/Windows/Fonts/segoeuib.ttf")

    def footer(self):
        self.set_y(-15)
        self.set_font("Segoe", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def clean(text):
    """Remove markdown bold/code markers for plain text output."""
    text = re.sub(r'\*\*', '', text)
    text = re.sub(r'`([^`]*)`', r'\1', text)
    return text.strip()


def write_bullet(pdf, text, line_height=5.5):
    """Write a bullet point with hanging indent so wrapped lines align."""
    original_l_margin = pdf.l_margin
    bullet_x = original_l_margin + BULLET_INDENT
    text_x = original_l_margin + BULLET_TEXT_INDENT

    # Draw bullet
    pdf.set_x(bullet_x)
    pdf.set_font("Segoe", "", 10)
    pdf.set_text_color(*BLACK)
    pdf.cell(BULLET_TEXT_INDENT - BULLET_INDENT, line_height, chr(8226))

    # Temporarily shift left margin so fpdf's internal wrapping aligns correctly
    pdf.set_left_margin(text_x)
    pdf.set_x(text_x)

    # Build rich text segments
    tokens = re.split(r'(\*\*.*?\*\*|`[^`]*`)', text)
    segments = []
    for token in tokens:
        if not token:
            continue
        if token.startswith("**") and token.endswith("**"):
            segments.append(("B", token[2:-2]))
        elif token.startswith("`") and token.endswith("`"):
            segments.append(("I", token[1:-1]))
        else:
            segments.append(("", token))

    # Render segments with inline formatting
    for style, seg in segments:
        if style == "B":
            pdf.set_font("Segoe", "B", 10)
            pdf.set_text_color(*DARK)
        elif style == "I":
            pdf.set_font("Segoe", "I", 9.5)
            pdf.set_text_color(60, 60, 60)
        else:
            pdf.set_font("Segoe", "", 10)
            pdf.set_text_color(*BLACK)
        pdf.write(line_height, seg)

    pdf.ln(line_height + 2)

    # Restore original left margin
    pdf.set_left_margin(original_l_margin)


def build_pdf(md_text):
    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=22)

    lines = md_text.split("\n")
    i = 0

    # --- Title page ---
    pdf.add_page()

    # Skip to title
    while i < len(lines):
        if lines[i].strip().startswith("# "):
            break
        i += 1

    # Title
    title = lines[i].strip()[2:]
    pdf.set_font("Segoe", "B", 24)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 14, title, new_x="LMARGIN", new_y="NEXT")
    # Title underline
    pdf.set_draw_color(*DARK)
    pdf.set_line_width(0.8)
    y = pdf.get_y() + 1
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(10)
    i += 1

    # --- Process all sections ---
    first_section = True
    while i < len(lines):
        line = lines[i].strip()

        # Skip blank lines
        if not line:
            i += 1
            continue

        # Skip separators
        if line == "---":
            i += 1
            continue

        # Section heading → new page (except first which shares with title)
        if line.startswith("## "):
            if not first_section:
                pdf.add_page()
            first_section = False
            pdf.set_font("Segoe", "B", 17)
            pdf.set_text_color(*BLUE)
            heading = line[3:].strip()
            pdf.multi_cell(0, 11, heading)
            pdf.ln(5)
            i += 1
            continue

        # Sub-section bold headers like "**Parsing adaptations:**" or "**Node types:**"
        if line.startswith("**") and line.endswith(":**"):
            pdf.ln(3)
            pdf.set_font("Segoe", "B", 11)
            pdf.set_text_color(*BLUE)
            pdf.cell(0, 7, clean(line), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
            i += 1
            continue

        # Bold-prefixed paragraph (Stage N, or **Label:** description)
        if line.startswith("**") and ":" in line and not line.startswith("**Key") and not line.startswith("**They"):
            pdf.ln(2)
            bold_match = re.match(r'\*\*(.*?)\*\*(.*)', line)
            if bold_match:
                label = bold_match.group(1)
                rest = bold_match.group(2).strip()
                rest = re.sub(r'`([^`]*)`', r'\1', rest)
                pdf.set_font("Segoe", "B", 10)
                pdf.set_text_color(*DARK)
                # Calculate hanging indent: label width
                label_w = pdf.get_string_width(label + " ")
                pdf.write(6, label)
                if rest:
                    pdf.set_font("Segoe", "", 10)
                    pdf.set_text_color(*BLACK)
                    # Write rest with word wrapping, hanging indent at label width
                    rest_text = " " + rest if not rest.startswith(" ") else rest
                    words = rest_text.split(' ')
                    for j, word in enumerate(words):
                        if j > 0:
                            word = ' ' + word
                        w = pdf.get_string_width(word)
                        if pdf.get_x() + w > pdf.w - pdf.r_margin:
                            pdf.ln(6)
                            pdf.set_x(pdf.l_margin)
                        pdf.write(6, word)
                pdf.ln(8)
            else:
                pdf.set_font("Segoe", "B", 10)
                pdf.set_text_color(*DARK)
                pdf.multi_cell(0, 6, clean(line))
                pdf.ln(3)
            i += 1
            continue

        # Key insight / key idea / key takeaway / They're complementary
        if line.startswith("**Key ") or line.startswith("**They"):
            pdf.ln(4)
            pdf.set_font("Segoe", "BI", 10)
            pdf.set_text_color(*BLUE)
            pdf.multi_cell(0, 6, clean(line))
            pdf.ln(4)
            i += 1
            continue

        # Bullet point
        if line.startswith("- "):
            text = line[2:].strip()
            write_bullet(pdf, text)
            i += 1
            continue

        # Regular paragraph
        pdf.set_font("Segoe", "", 10)
        pdf.set_text_color(*BLACK)
        pdf.multi_cell(0, 6, clean(line))
        pdf.ln(3)
        i += 1

    pdf.output(PDF_PATH)
    print(f"PDF generated: {PDF_PATH}")


build_pdf(md_text)
