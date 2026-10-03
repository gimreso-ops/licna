"""
Izjava birača – popunjavanje obrasca sa lične karte.

Ništa se ne čuva: podaci postoje samo dok su na ekranu i brišu se
kada se kartica izvadi ili se klikne "Očisti".
"""
import configparser
import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QPainter, QPageSize, QKeySequence, QShortcut
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo, QPrintPreviewDialog
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from obrazac import Obrazac
from provera import ProveraSpiska

try:
    import citac_lk
    IMA_CITAC = True
except Exception:          # nema pyscard ili PC/SC servisa – radi ručni unos
    citac_lk = None
    IMA_CITAC = False


def putanja(ime):
    """Prvo pored .exe (da se obrazac može zameniti), pa ugrađeni."""
    baza = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                           else os.path.abspath(__file__))
    p = os.path.join(baza, ime)
    if os.path.exists(p):
        return p
    return os.path.join(getattr(sys, "_MEIPASS", baza), ime)


def ucitaj_config():
    c = configparser.ConfigParser()
    c.read(putanja("config.ini"), encoding="utf-8")
    s = c["stampa"] if c.has_section("stampa") else {}
    return {
        "obrazac": s.get("obrazac", "obrazac.pdf"),
        "papir": s.get("papir", "A4").upper(),
        "dx": float(s.get("pomeraj_x_mm", 0)),
        "dy": float(s.get("pomeraj_y_mm", 0)),
        "velicina": float(s.get("velicina_slova", 10)),
    }


POLJA = [
    ("ime_prezime", "Ime i prezime"),
    ("jmbg", "JMBG"),
    ("datum_rodjenja", "Datum rođenja"),
    ("mesto", "Mesto"),
    ("ulica", "Ulica i broj"),
    ("dokument", "Lični dokument"),
]


class Prozor(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.obrazac = Obrazac(putanja(cfg["obrazac"]))
        self.pozadina = self.obrazac.slika(300)
        self.atr = None          # ATR trenutno ubačene kartice
        self.brojac = 0

        self.setWindowTitle("Izjava birača – popunjavanje sa lične karte")
        self.resize(1250, 700)
        glavni = QHBoxLayout(self)
        levo = QWidget()
        levo.setFixedWidth(520)
        v = QVBoxLayout(levo)
        glavni.addWidget(levo)
        self.web = ProveraSpiska()
        glavni.addWidget(self.web, 1)

        self.status = QLabel()
        f = QFont(); f.setPointSize(13); f.setBold(True)
        self.status.setFont(f)
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        forma = QFormLayout()
        self.stampac = QComboBox()
        imena = [p.printerName() for p in QPrinterInfo.availablePrinters()]
        self.stampac.addItems(imena)
        pod = QPrinterInfo.defaultPrinter().printerName()
        if pod in imena:
            self.stampac.setCurrentText(pod)
        forma.addRow("Štampač", self.stampac)

        self.edit = {}
        for k, naziv in POLJA:
            e = QLineEdit()
            self.edit[k] = e
            forma.addRow(naziv, e)
        v.addLayout(forma)

        self.klauzula = QCheckBox("Popuni i klauzulu o overi (ime, datum rođenja, adresa, dokument)")
        self.klauzula.setChecked(True)
        v.addWidget(self.klauzula)

        h = QHBoxLayout()
        b_pregled = QPushButton("Pregled")
        b_ocisti = QPushButton("Očisti")
        b_dijag = QPushButton("Dijagnostika")
        b_spisak = QPushButton("Proveri u spisku")
        self.b_stampaj = QPushButton("Štampaj  (F9)")
        self.b_stampaj.setDefault(True)
        self.b_stampaj.setMinimumHeight(40)
        h.addWidget(b_pregled); h.addWidget(b_ocisti); h.addWidget(b_dijag); h.addWidget(b_spisak); h.addStretch(); h.addWidget(self.b_stampaj)
        v.addLayout(h)

        self.info = QLabel()
        self.info.setStyleSheet("color: gray")
        v.addWidget(self.info)
        v.addStretch()

        b_pregled.clicked.connect(self.pregled)
        b_ocisti.clicked.connect(self.ocisti)
        b_dijag.clicked.connect(self.dijagnostika)
        self.b_stampaj.clicked.connect(self.stampaj)
        b_spisak.clicked.connect(self.proveri_spisak)
        # F9 radi svuda; Enter samo u levom delu (u stranici Enter šalje upit)
        QShortcut(QKeySequence(Qt.Key_F9), self, self.stampaj)
        for kljuc in (Qt.Key_Return, Qt.Key_Enter):
            sc = QShortcut(QKeySequence(kljuc), levo, self.stampaj)
            sc.setContext(Qt.WidgetWithChildrenShortcut)

        nedostaju = self.obrazac.nedostaju()
        if nedostaju:
            QMessageBox.warning(self, "Obrazac",
                                "Na obrascu nisu pronađena polja: " + ", ".join(nedostaju))

        if IMA_CITAC:
            self.set_status("Ubacite ličnu kartu u čitač…")
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.proveri_citac)
            self.timer.start(700)
        else:
            self.set_status("Čitač nije dostupan – moguć je ručni unos.", "darkred")

    # ---------------------------------------------------------- čitač
    def set_status(self, tekst, boja="black"):
        self.status.setText(tekst)
        self.status.setStyleSheet(f"color: {boja}")

    def proveri_citac(self):
        citaci = citac_lk.spisak_citaca()
        if not citaci:
            self.set_status("Čitač nije povezan.", "darkred")
            self.atr = None
            return
        atr = citac_lk.kartica_prisutna(citaci[0])
        if atr is None:
            if self.atr is not None:          # kartica izvađena → obriši sve
                self.ocisti()
            self.atr = None
            if not any(e.text() for e in self.edit.values()):
                self.set_status("Ubacite ličnu kartu u čitač…")
            return
        if atr == self.atr:
            return
        self.atr = atr
        # Windows posle ubacivanja kartice nakratko sam pristupa čipu –
        # sačekamo ga da završi, pa tek onda čitamo.
        self.set_status("Kartica ubačena, čitam…", "navy")
        self.timer.stop()
        QTimer.singleShot(1500, self.procitaj_karticu)

    def procitaj_karticu(self):
        try:
            self._procitaj_karticu()
        finally:
            self.timer.start(700)

    def _procitaj_karticu(self):
        citaci = citac_lk.spisak_citaca()
        if not citaci:
            return
        QApplication.processEvents()
        try:
            lk = citac_lk.procitaj(citaci[0])
        except Exception as ex:
            self.set_status(f"Greška pri čitanju: {ex}", "darkred")
            return
        self.popuni({
            "ime_prezime": lk.ime_prezime,
            "jmbg": lk.get("jmbg"),
            "datum_rodjenja": lk.datum_rodjenja,
            "mesto": lk.mesto,
            "ulica": lk.ulica_broj,
            "dokument": lk.dokument,
        })
        if citac_lk.jmbg_ispravan(lk.get("jmbg")):
            self.set_status(f"Očitano: {lk.ime_prezime}. Prepišite tekst sa slike desno "
                            "i proverite spisak, pa štampajte (F9).", "darkgreen")
            self.web.proveri(lk.get("jmbg"))
        else:
            self.set_status("Očitano, ali JMBG nije ispravan – proverite!", "darkred")

    def dijagnostika(self):
        """Prikazuje sve podatke sa čipa (zamena za 'citac_lk.py --dump')."""
        if not IMA_CITAC:
            QMessageBox.warning(self, "Dijagnostika", "Biblioteka za čitač nije učitana.")
            return
        citaci = citac_lk.spisak_citaca()
        tekst = "Čitači: " + (", ".join(str(c) for c in citaci) or "nema") + "\n"
        if citaci:
            atr = citac_lk.kartica_prisutna(citaci[0])
            tekst += "ATR: " + (atr.hex(" ").upper() if atr else "nema kartice") + "\n\n"
            try:
                lk = citac_lk.procitaj(citaci[0])
                for t, v in sorted(lk.sirovo.items()):
                    tekst += f"{t}  {citac_lk.TAGS.get(t, '?')}:  {v}\n"
            except Exception as ex:
                tekst += f"Greška: {ex}"
        m = QMessageBox(self)
        m.setWindowTitle("Dijagnostika")
        m.setText("Podaci sa kartice (samo prikaz, ništa se ne čuva):")
        m.setDetailedText(tekst)
        m.exec()

    def proveri_spisak(self):
        jmbg = self.edit["jmbg"].text().strip()
        if len(jmbg) != 13 or not jmbg.isdigit():
            QMessageBox.information(self, "Provera", "Unesite ispravan JMBG (13 cifara).")
            return
        self.web.proveri(jmbg)

    def popuni(self, d):
        for k, e in self.edit.items():
            v = d.get(k, "")
            if IMA_CITAC and k != "jmbg":
                v = citac_lk.u_cirilicu(v)
            e.setText(v)

    def podaci(self):
        d = {k: e.text().strip() for k, e in self.edit.items()}
        if IMA_CITAC:                       # sve što se štampa – ćirilicom
            d = {k: (v if k == "jmbg" else citac_lk.u_cirilicu(v)) for k, v in d.items()}
        return d

    def ocisti(self):
        for e in self.edit.values():
            e.clear()
        self.web.prazno()
        self.set_status("Ubacite ličnu kartu u čitač…" if IMA_CITAC else "Ručni unos.")

    # ---------------------------------------------------------- štampa
    def napravi_printer(self, pdf=None):
        p = QPrinter(QPrinter.HighResolution)
        if pdf:
            p.setOutputFormat(QPrinter.PdfFormat)
            p.setOutputFileName(pdf)
        elif self.stampac.currentText():
            p.setPrinterName(self.stampac.currentText())
        p.setPageSize(QPageSize(QPageSize.Letter if self.cfg["papir"] == "LETTER"
                                else QPageSize.A4))
        p.setFullPage(True)
        return p

    def crtaj(self, printer):
        painter = QPainter(printer)
        self.obrazac.nacrtaj(painter, printer, self.podaci(), self.pozadina,
                             self.cfg["dx"], self.cfg["dy"], self.cfg["velicina"],
                             self.klauzula.isChecked())
        painter.end()

    def proveri_pre_stampe(self):
        d = self.podaci()
        if not d["ime_prezime"]:
            QMessageBox.information(self, "Štampa", "Nema podataka za štampu.")
            return False
        if IMA_CITAC and not citac_lk.jmbg_ispravan(d["jmbg"]):
            return QMessageBox.question(self, "JMBG",
                                        "JMBG nije ispravan. Ipak štampati?") == QMessageBox.Yes
        return True

    def stampaj(self):
        if not self.proveri_pre_stampe():
            return
        self.crtaj(self.napravi_printer())
        self.brojac += 1
        self.info.setText(f"Odštampano u ovoj sesiji: {self.brojac}")
        self.set_status("Poslato na štampu. Izvadite karticu za sledećeg birača.", "darkgreen")

    def pregled(self):
        dlg = QPrintPreviewDialog(self.napravi_printer(), self)
        dlg.paintRequested.connect(self.crtaj)
        dlg.resize(800, 1000)
        dlg.exec()


def main():
    app = QApplication(sys.argv)
    w = Prozor(ucitaj_config())
    if "--test" in sys.argv:        # probni podaci, za podešavanje pozicija
        w.popuni({"ime_prezime": "Петар Петровић", "jmbg": "0101990800007",
                  "datum_rodjenja": "01.01.1990.", "mesto": "Сомбор",
                  "ulica": "Венац војводе Петра Бојовића 12а, стан 4",
                  "dokument": "личну карту бр. 012345678, издату 15.03.2021., ПУ ЗА ГРАД СОМБОР"})
        if "--pdf" in sys.argv:
            w.crtaj(w.napravi_printer(sys.argv[sys.argv.index("--pdf") + 1]))
            return
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
