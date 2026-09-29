"""
Pronalaženje polja na obrascu (PDF) i crtanje podataka preko njega.

Pozicije se NE unose ručno: program u PDF-u traži oznake kao što su
"(име и презиме)", "(ЈМБГ)", "увидом у" i crte "_____" pored njih.
Zato radi i ako obrazac izvezete iz Word-a sa malo drugačijim rasporedom.
"""
import re
import pymupdf
from PySide6.QtCore import QRectF, QPointF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QImage, QPainter

FONT = "Arial"


class Slot:
    """Horizontalna crta na koju se upisuje tekst (koordinate u pt)."""
    def __init__(self, x0, x1, baseline):
        self.x0, self.x1, self.baseline = x0, x1, baseline

    def __repr__(self):
        return f"Slot({self.x0:.0f}-{self.x1:.0f} @ {self.baseline:.0f})"


class Obrazac:
    def __init__(self, putanja):
        self.doc = pymupdf.open(putanja)
        self.page = self.doc[0]
        self.w, self.h = self.page.rect.width, self.page.rect.height
        self._crte = self._nadji_crte()
        self.polja = self._nadji_polja()

    # ---------------------------------------------------------- analiza
    def _nadji_crte(self):
        crte = []
        for b in self.page.get_text("rawdict")["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    run = []
                    for c in s["chars"] + [None]:
                        if c is not None and c["c"] == "_":
                            run.append(c)
                            continue
                        if len(run) >= 5:
                            crte.append(Slot(run[0]["bbox"][0], run[-1]["bbox"][2],
                                             s["origin"][1]))
                        run = []
        return crte

    def _oznake(self, tekst, min_sirina=15):
        r = [x for x in self.page.search_for(tekst) if x.width > min_sirina]
        return sorted(r, key=lambda x: (x.y0, x.x0))

    def _crta_iznad(self, oznaka, preskoci=0):
        kand = [c for c in self._crte
                if c.baseline < oznaka.y0 + 1 and c.x0 < oznaka.x1 and c.x1 > oznaka.x0]
        kand.sort(key=lambda c: -c.baseline)
        return kand[preskoci] if len(kand) > preskoci else None

    def _crta_desno(self, oznaka):
        kand = [c for c in self._crte
                if abs(c.baseline - (oznaka.y1 - 3)) < 6 and c.x1 > oznaka.x1]
        kand.sort(key=lambda c: c.x0)
        return kand[0] if kand else None

    def _crta_ispod(self, slot):
        kand = [c for c in self._crte if 5 < c.baseline - slot.baseline < 25]
        kand.sort(key=lambda c: c.baseline)
        return kand[0] if kand else None

    def _jmbg_polja(self, oznaka):
        xs = set()
        y0 = y1 = None
        for d in self.page.get_drawings():
            for it in d["items"]:
                if it[0] != "l":
                    continue
                p1, p2 = it[1], it[2]
                if abs(p1.x - p2.x) < 0.5 and 5 < abs(p1.y - p2.y) < 30 \
                        and oznaka.y0 - 30 < max(p1.y, p2.y) <= oznaka.y0 + 2:
                    xs.add(round(p1.x, 1))
                    y0, y1 = min(p1.y, p2.y), max(p1.y, p2.y)
        xs = sorted(xs)
        if len(xs) != 14:
            return None
        return [QRectF(xs[i], y0, xs[i + 1] - xs[i], y1 - y0) for i in range(13)]

    def _nadji_polja(self):
        p = {}
        ime = self._oznake("(име и презиме)")
        adr = self._oznake("(место и адреса пребивалишта)")
        jm = self._oznake("(ЈМБГ)")
        if ime:
            p["birac_ime"] = [self._crta_iznad(ime[0])]
        if jm:
            p["birac_jmbg"] = self._jmbg_polja(jm[0])
        if adr:
            p["birac_adresa"] = [self._crta_iznad(adr[0], 1), self._crta_iznad(adr[0], 0)]
        pot = self._oznake("Потврђује се да је")
        if pot:
            p["overa_ime"] = [self._crta_desno(pot[0])]
        rod = self._oznake("рођен/а")
        if rod:
            p["overa_datum"] = [self._crta_desno(rod[0])]
        iz = [r for r in self._oznake("из", 5) if pot and 0 < r.y0 - pot[0].y0 < 40 and r.x0 < 100]
        if iz:
            p["overa_adresa"] = [self._crta_desno(iz[0])]
        uv = self._oznake("увидом у")
        if uv:
            s1 = self._crta_desno(uv[0])
            p["overa_dokument"] = [s1, self._crta_ispod(s1) if s1 else None]
        return {k: v for k, v in p.items() if v and all(v)}

    def nedostaju(self):
        sva = ["birac_ime", "birac_jmbg", "birac_adresa",
               "overa_ime", "overa_datum", "overa_adresa", "overa_dokument"]
        return [k for k in sva if k not in self.polja]

    def slika(self, dpi=300):
        pix = self.page.get_pixmap(dpi=dpi, alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format_RGB888)
        return img.copy()

    # ---------------------------------------------------------- crtanje
    def nacrtaj(self, painter: QPainter, uredjaj, podaci: dict, pozadina: QImage,
                dx_mm=0.0, dy_mm=0.0, velicina=10.0, klauzula=True):
        """Crta obrazac + podatke na QPrinter. Stranica se skalira da stane (A4/Letter)."""
        page_px = uredjaj.pageLayout().fullRectPixels(uredjaj.resolution())
        k = min(page_px.width() / self.w, page_px.height() / self.h)
        ox = (page_px.width() - self.w * k) / 2
        oy = 0.0
        mm = uredjaj.resolution() / 25.4
        ox += dx_mm * mm
        oy += dy_mm * mm

        def P(x, y):
            return QPointF(ox + x * k, oy + y * k)

        if pozadina is not None:
            painter.drawImage(QRectF(ox, oy, self.w * k, self.h * k), pozadina)

        painter.setPen(Qt.black)
        skala = self.w * k / (self.w * uredjaj.resolution() / 72)  # odnos skaliranja

        def font(sz):
            f = QFont(FONT)
            f.setPointSizeF(sz * skala)
            return f

        def upisi(slot, tekst, centar=False):
            if not tekst:
                return
            sz = velicina
            sirina = (slot.x1 - slot.x0) * k
            while True:
                f = font(sz)
                fm = QFontMetricsF(f, uredjaj)
                w = fm.horizontalAdvance(tekst)
                if w <= sirina - 4 * k or sz <= 6:
                    break
                sz -= 0.5
            painter.setFont(f)
            x = slot.x0 + 3 if not centar else slot.x0 + ((slot.x1 - slot.x0) - w / k) / 2
            painter.drawText(P(x, slot.baseline - 2.5), tekst)

        def upisi_vise(slotovi, tekst):
            """Prelama tekst preko više crta."""
            reci = tekst.split()
            for i, slot in enumerate(slotovi):
                if not reci:
                    return
                if i == len(slotovi) - 1:
                    upisi(slot, " ".join(reci))
                    return
                fm = QFontMetricsF(font(velicina), uredjaj)
                sirina = (slot.x1 - slot.x0 - 6) * k
                red = []
                while reci and fm.horizontalAdvance(" ".join(red + [reci[0]])) <= sirina:
                    red.append(reci.pop(0))
                if not red:
                    red.append(reci.pop(0))
                upisi(slot, " ".join(red))

        pl = self.polja
        if "birac_ime" in pl:
            upisi(pl["birac_ime"][0], podaci.get("ime_prezime", ""), centar=True)
        if "birac_adresa" in pl:
            upisi(pl["birac_adresa"][0], podaci.get("mesto", ""), centar=True)
            upisi(pl["birac_adresa"][1], podaci.get("ulica", ""), centar=True)
        if "birac_jmbg" in pl:
            jm = re.sub(r"\D", "", podaci.get("jmbg", ""))
            if len(jm) == 13:
                painter.setFont(font(velicina + 1))
                for rect, cif in zip(pl["birac_jmbg"], jm):
                    r = QRectF(P(rect.x(), rect.y()), P(rect.right(), rect.bottom()))
                    painter.drawText(r, Qt.AlignCenter, cif)
        if klauzula:
            if "overa_ime" in pl:
                upisi(pl["overa_ime"][0], podaci.get("ime_prezime", ""), centar=True)
            if "overa_datum" in pl:
                upisi(pl["overa_datum"][0], podaci.get("datum_rodjenja", ""), centar=True)
            if "overa_adresa" in pl:
                adresa = ", ".join(x for x in (podaci.get("mesto"), podaci.get("ulica")) if x)
                upisi(pl["overa_adresa"][0], adresa)
            if "overa_dokument" in pl:
                upisi_vise(pl["overa_dokument"], podaci.get("dokument", ""))
