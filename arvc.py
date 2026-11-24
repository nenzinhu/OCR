import argparse
import json
import re
import subprocess
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

PORTAL = "https://portal.pmrv.sc.gov.br/portal/"

SECTIONS = {
    1: ("Retenção", {"protocolo n": "Protocolo RADAR (confirmar)"}),
    2: ("Motivo de Recolhimento/Infrações", {"motivo": "Motivo (conferência manual)"}),
    3: ("Veículo", dict(zip(
        ("placa", "municipio", "marca/modelo", "especie", "tipo", "categoria"),
        ("Placa", "Município", "Marca/Modelo", "Espécie", "Tipo", "Categoria"),
    ))),
    4: ("Condutor", {"nome": "Nome", "cpf": "CPF", "telefone": "Telefone"}),
    5: ("Proprietário", {"nome": "Nome/Razão social", "cpf/cnpj": "CPF/CNPJ"}),
    6: ("Retenção", {"data": "Data retenção", "hora": "Hora"}),
    8: ("Transporte/Guinchamento", {
        "meio de transporte": "Tipo transporte", "nome do motorista": "Motorista",
        "empresa/opm": "Empresa/OPM (confirmar)",
    }),
}
TAB_ORDER = (
    "Retenção", "Veículo", "Proprietário", "Condutor",
    "Transporte/Guinchamento", "Motivo de Recolhimento/Infrações",
)
ADDRESS = dict(endereco="Logradouro", numero="N.º", complemento="Complemento",
               municipio="Município", cep="CEP", bairro="Bairro")


def normalize(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                   if not unicodedata.combining(c))


def extract(source):
    sections = {}
    section = None
    for line in source.splitlines():
        line = line.strip()
        heading = re.match(r"^(1[01]|[1-9])[.)]\s*[\W_]*[A-Za-z]", line)
        if heading:
            section = int(heading[1])
        elif line and section:
            sections.setdefault(section, []).append(line)
    result = {}
    for number, (tab, labels) in SECTIONS.items():
        labels = labels | ADDRESS if number in (4, 5) else labels
        fields = result.setdefault(tab, {})
        for index, line in enumerate(sections.get(number, [])):
            match = re.match(r"^([^:]+):\s*(.+)$", line)
            if match:
                key = labels.get(normalize(match[1].strip()))
                value = match[2].strip()
                if key and normalize(value) not in ("nao informado", "nao informada", ".", "-"):
                    if key in ("Marca/Modelo", "Motivo (conferência manual)"):
                        continuation = sections[number][index + 1:]
                        for extra in continuation:
                            if ":" in extra:
                                break
                            value += " " + extra
                    fields[key] = value
    retention = result["Retenção"]
    for line in sections.get(1, []):
        match = re.fullmatch(r"ARVC\s*[:.-]?\s*([a-z0-9]+)", line, re.I)
        if match:
            retention["N.º do ARVC"] = match[1].upper()
    for line in sections.get(6, []):
        match = re.search(r"^Local:\s*(\S+(?:\s+\d+)?)\s+Km\s*([\d.,]+)", line, re.I)
        if match:
            retention["Rodovia"] = match[1].replace(" ", "")
            retention["Km"] = match[2].replace(".", ",")
    if re.fullmatch(r"\d{2}:\d{2}:\d{2}", retention.get("Hora", "")):
        retention["Hora"] = retention["Hora"][:5]
    if sections.get(9):
        retention["Observações"] = " ".join(sections[9])
    for line in sections.get(10, []):
        match = re.match(r"matricula:\s*(\d+)", normalize(line))
        if match:
            retention["Matrícula do responsável"] = match[1]
    return {tab: result[tab] for tab in TAB_ORDER if result.get(tab)}


def portal_frame(frame):
    origin = urlsplit(frame.url)
    return origin.scheme == "https" and origin.hostname == "portal.pmrv.sc.gov.br"


ACTIVE_FIELD = """() => {
    const field = document.activeElement;
    if (!field?.matches('input, textarea, select') ||
        field.matches('input[type=hidden], input[type=password], input[type=button], input[type=submit], input[type=reset], input[type=file], input[type=checkbox], input[type=radio]')) return null;
    for (const attr of ['id', 'name']) {
        const value = field.getAttribute(attr);
        if (!value) continue;
        const selector = field.localName + '[' + attr + '=' + CSS.escape(value) + ']';
        if (document.querySelectorAll(selector).length === 1) return selector;
    }
    return null;
}"""


def find_control(page, selector):
    matches = [control for frame in page.frames if portal_frame(frame)
               for control in frame.locator(selector).all() if control.is_visible()]
    return matches[0] if len(matches) == 1 else None


def fill_portal(data, mapping_path, ask=input, report=print):
    from playwright.sync_api import Error, sync_playwright

    mapping = json.loads(mapping_path.read_text(encoding="utf-8")) if mapping_path.exists() else {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(PORTAL, wait_until="domcontentloaded")
        ask("Entre no portal e abra o cadastro. Depois pressione Enter aqui. ")
        for tab, fields in data.items():
            if not fields:
                continue
            if tab == "Motivo de Recolhimento/Infrações":
                report(f"Preencha o motivo no portal após conferir: {fields}")
                continue
            command = ask(f"Abra a aba {tab} e pressione Enter, ou digite p para pular: ")
            if command.strip().lower() == "p":
                continue
            tab_mapping = mapping.setdefault(tab, {})
            for label, value in fields.items():
                if "(confirmar)" in label:
                    continue
                selector = tab_mapping.get(label)
                control = find_control(page, selector) if selector else None
                if control is None:
                    command = ask(f"Clique no campo {label} no portal e pressione Enter aqui, ou p para pular: ")
                    if command.strip().lower() == "p":
                        continue
                    selectors = [frame.evaluate(ACTIVE_FIELD) for frame in page.frames if portal_frame(frame)]
                    found = [candidate for candidate in selectors if candidate]
                    selector = found[0] if len(found) == 1 else None
                    control = find_control(page, selector) if selector else None
                if control is None:
                    report(f"Campo {label} pendente.")
                    continue
                try:
                    if control.evaluate("(field) => field.localName") == "select":
                        control.select_option(label=value, timeout=2000)
                    elif control.is_editable():
                        existing = control.input_value(timeout=2000).strip()
                        if existing and existing != value:
                            replace = ask(f"{label} já tem um valor. Substituir? [s/N] ")
                            if replace.strip().lower() != "s":
                                continue
                        control.fill(value, timeout=2000)
                        control.blur(timeout=2000)
                    else:
                        report(f"Campo {label} exige preenchimento manual.")
                        continue
                except Error:
                    report(f"Confira o campo {label} no portal.")
                    continue
                tab_mapping[label] = selector
                mapping_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
        ask("Confira o cadastro e salve pelo portal. Pressione Enter aqui para fechar o navegador. ")


def choose_image():
    from tkinter import Tk, filedialog

    window = Tk()
    window.withdraw()
    try:
        selected = filedialog.askopenfilename(
            parent=window,
            title="Anexar imagem do ARVC",
            filetypes=[("Imagens", "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp")],
        )
        return Path(selected) if selected else None
    finally:
        window.destroy()


def read_image(image, executable="tesseract"):
    try:
        run = subprocess.run(
            [executable, str(image.resolve()), "stdout", "-l", "por", "--psm", "6"],
            capture_output=True, check=True,
        )
    except FileNotFoundError:
        raise RuntimeError("Tesseract não encontrado. Instale-o ou informe o caminho do executável.") from None
    except subprocess.CalledProcessError as error:
        raise RuntimeError(error.stderr.decode("utf-8", errors="replace").strip()) from error
    source = run.stdout.decode("utf-8")
    data = extract(source)
    return source, data


def main():
    parser = argparse.ArgumentParser(description="OCR local e preenchimento assistido de ARVC.")
    parser.add_argument("imagem", type=Path, nargs="?", help="Imagem do ARVC. Se omitida, abre o seletor e inicia o fluxo do portal.")
    parser.add_argument("--tesseract", default="tesseract")
    parser.add_argument("--portal", action="store_true")
    parser.add_argument("--mapa", type=Path, default=Path("arvc-mapa.json"))
    args = parser.parse_args()
    use_portal = args.portal or args.imagem is None
    image = args.imagem if args.imagem is not None else choose_image()
    if image is None:
        return
    if not image.is_file():
        parser.error(f"Imagem não encontrada: {image}")
    try:
        source, data = read_image(image, args.tesseract)
    except RuntimeError as error:
        parser.exit(1, str(error) + "\n")
    print(source)
    if not data:
        parser.exit(1, "Nenhum campo reconhecido. Confira o texto acima e a qualidade da imagem.\n")
    for tab, fields in data.items():
        print(f"\n{tab}")
        for label, value in fields.items():
            print(f"  {label}: {value}")
    if use_portal:
        if input("\nRevisar e abrir o portal? [s/N] ").strip().lower() != "s":
            return
        for fields in data.values():
            for label in list(fields):
                correction = input(f"{label} [{fields[label]}] (Enter mantém, - remove): ").strip()
                if correction == "-":
                    del fields[label]
                elif correction:
                    fields[label] = correction
        fill_portal(data, args.mapa)


if __name__ == "__main__":
    main()
