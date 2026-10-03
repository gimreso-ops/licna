"""
Čitanje srpske lične karte sa čipom (PC/SC čitač).

Podržane kartice:
  - Apollo (lične karte izdate 2008–2014)
  - Gemalto (2014+)
  - nove kartice (2020+/2023+), sa drugim AID-om

Osnovni podaci se čitaju BEZ PIN-a.
Pokretanje za dijagnostiku:  python citac_lk.py --dump
"""
import sys
import time
from dataclasses import dataclass, field

from smartcard.System import readers
from smartcard.Exceptions import NoCardException, CardConnectionException
from smartcard.scard import SCARD_SHARE_EXCLUSIVE, SCARD_RESET_CARD

AIDS = [
    [0xF3, 0x81, 0x00, 0x00, 0x02, 0x53, 0x45, 0x52, 0x49, 0x44, 0x01],  # Gemalto 2014+
    [0xA0, 0x00, 0x00, 0x00, 0x77, 0x01, 0x08, 0x00, 0x07, 0x00, 0x00,
     0xFE, 0x00, 0x00, 0x01, 0x00],                                      # novije kartice
]
FILE_DOCUMENT = [0x0F, 0x02]
FILE_PERSONAL = [0x0F, 0x03]
FILE_RESIDENCE = [0x0F, 0x04]

# TLV tagovi
TAGS = {
    1546: "broj_dokumenta", 1547: "tip_dokumenta", 1548: "datum_izdavanja",
    1549: "vazi_do", 1550: "izdavalac",
    1558: "jmbg", 1559: "prezime", 1560: "ime", 1561: "ime_roditelja",
    1562: "pol", 1563: "mesto_rodjenja", 1564: "opstina_rodjenja",
    1565: "drzava_rodjenja", 1566: "datum_rodjenja",
    1568: "drzava", 1569: "opstina", 1570: "mesto", 1571: "ulica",
    1572: "broj", 1573: "slovo", 1574: "ulaz", 1575: "sprat",
    1578: "stan", 1580: "datum_prijave_adrese",
}


LAT_CIR = [
    ("DŽ", "Џ"), ("Dž", "Џ"), ("dž", "џ"), ("LJ", "Љ"), ("Lj", "Љ"), ("lj", "љ"),
    ("NJ", "Њ"), ("Nj", "Њ"), ("nj", "њ"),
]
LAT_CIR_1 = dict(zip(
    "ABCČĆDĐEFGHIJKLMNOPRSŠTUVZŽabcčćdđefghijklmnoprsštuvzž",
    "АБЦЧЋДЂЕФГХИЈКЛМНОПРСШТУВЗЖабцчћдђефгхијклмнопрсштувзж"))
# slova kojih nema u srpskoj latinici (strana imena) – približno, operater može da ispravi
LAT_CIR_1.update({"Q": "К", "q": "к", "W": "В", "w": "в", "Y": "И", "y": "и",
                  "Ä": "Е", "ä": "е", "Ö": "Е", "ö": "е", "Ü": "И", "ü": "и", "ß": "с"})


def u_cirilicu(tekst):
    """Srpska latinica → ćirilica. Ćirilica i brojevi ostaju nepromenjeni."""
    if not tekst:
        return ""
    for lat, cir in LAT_CIR:
        tekst = tekst.replace(lat, cir)
    tekst = tekst.replace("X", "КС").replace("x", "кс")
    return "".join(LAT_CIR_1.get(c, c) for c in tekst)


class CitacGreska(Exception):
    pass


@dataclass
class LicnaKarta:
    polja: dict = field(default_factory=dict)
    sirovo: dict = field(default_factory=dict)   # svi tagovi (za --dump)

    def get(self, k):
        return (self.polja.get(k) or "").strip()

    @staticmethod
    def datum(s):
        s = (s or "").strip()
        if len(s) == 8 and s.isdigit():            # DDMMYYYY
            return f"{s[0:2]}.{s[2:4]}.{s[4:8]}."
        return s

    @property
    def ime_prezime(self):
        return f"{self.get('ime')} {self.get('prezime')}".strip()

    @property
    def datum_rodjenja(self):
        d = self.datum(self.get("datum_rodjenja"))
        if not d:
            d = datum_iz_jmbg(self.get("jmbg"))
        return d

    @property
    def mesto(self):
        mesto, opstina = self.get("mesto"), self.get("opstina")
        if opstina and opstina.upper() != mesto.upper():
            return f"{mesto}, {opstina}" if mesto else opstina
        return mesto

    @property
    def ulica_broj(self):
        s = self.get("ulica")
        br = self.get("broj") + self.get("slovo")
        if br:
            s += f" {br}"
        if self.get("ulaz"):
            s += f", улаз {self.get('ulaz')}"
        if self.get("sprat"):
            s += f", спрат {self.get('sprat')}"
        if self.get("stan"):
            s += f", стан {self.get('stan')}"
        return s.strip(" ,")

    def _podaci_dokumenta(self):
        """Broj, datum izdavanja i izdavalac. Ako tagovi ne odgovaraju očekivanom
        (različite generacije kartica), podaci se prepoznaju po sadržaju."""
        broj = self.get("broj_dokumenta")
        datum = self.get("datum_izdavanja")
        izd = self.get("izdavalac")
        vrednosti = [(v or "").strip() for t, v in self.sirovo.items() if 1545 <= t <= 1557]
        datumi = sorted((v for v in vrednosti if len(v) == 8 and v.isdigit()),
                        key=lambda d: d[4:] + d[2:4] + d[:2])
        if datumi:
            datum = datumi[0]          # izdavanje je uvek pre isteka važenja
        if not (broj.isdigit() and len(broj) != 8):
            kand = [v for v in vrednosti if v.isdigit() and len(v) != 8]
            broj = kand[0] if kand else broj
        if not izd or izd.isdigit() or len(izd) <= 3:
            kand = [v for v in vrednosti if any(c.isalpha() for c in v) and len(v) > 3]
            izd = max(kand, key=len) if kand else ""
        return broj, datum, izd

    @property
    def dokument(self):
        broj, datum, izd = self._podaci_dokumenta()
        parts = ["личну карту"]
        if broj:
            parts[0] += f" бр. {broj}"
        if datum:
            parts.append(f"издату {self.datum(datum)}")
        if izd:
            parts.append(f"издавалац {u_cirilicu(izd)}")
        return ", ".join(parts)


def datum_iz_jmbg(jmbg):
    if len(jmbg) != 13 or not jmbg.isdigit():
        return ""
    dd, mm, ggg = jmbg[0:2], jmbg[2:4], int(jmbg[4:7])
    god = 1000 + ggg if ggg >= 800 else 2000 + ggg
    return f"{dd}.{mm}.{god}."


def jmbg_ispravan(jmbg):
    if len(jmbg) != 13 or not jmbg.isdigit():
        return False
    d = [int(c) for c in jmbg]
    m = 11 - ((7 * (d[0] + d[6]) + 6 * (d[1] + d[7]) + 5 * (d[2] + d[8])
               + 4 * (d[3] + d[9]) + 3 * (d[4] + d[10]) + 2 * (d[5] + d[11])) % 11)
    if m > 9:
        m = 0
    return m == d[12]


# ------------------------------------------------------------------ APDU

def _tx(conn, apdu):
    data, sw1, sw2 = conn.transmit(apdu)
    if sw1 == 0x61:                                   # ima još podataka
        more, sw1, sw2 = conn.transmit([0x00, 0xC0, 0x00, 0x00, sw2])
        data += more
    return data, sw1, sw2


def _ok(sw1, sw2):
    return (sw1, sw2) == (0x90, 0x00) or sw1 == 0x61


def _select(conn, name, p1, le=None):
    apdu = [0x00, 0xA4, p1, 0x00, len(name)] + name
    if le is not None:
        apdu.append(le)
    _, sw1, sw2 = _tx(conn, apdu)
    return _ok(sw1, sw2)


def _select_file(conn, name):
    return _select(conn, name, 0x08, 0x04) or _select(conn, name, 0x08)


def _read(conn, offset, length):
    apdu = [0x00, 0xB0, (offset >> 8) & 0xFF, offset & 0xFF, length]
    data, sw1, sw2 = _tx(conn, apdu)
    if sw1 == 0x6C:                                   # pogrešna dužina
        apdu[4] = sw2
        data, sw1, sw2 = _tx(conn, apdu)
    if not _ok(sw1, sw2) and not data:
        raise CitacGreska(f"READ BINARY greška {sw1:02X}{sw2:02X}")
    return data


def _read_file(conn, name):
    if not _select_file(conn, name):
        raise CitacGreska(f"Ne mogu da otvorim fajl {name[0]:02X}{name[1]:02X}")
    header = _read(conn, 0, 4)
    length = header[2] | (header[3] << 8)
    out, offset = [], 4
    while length > 0:
        chunk = _read(conn, offset, min(length, 0xFF))
        if not chunk:
            break
        out += chunk
        offset += len(chunk)
        length -= len(chunk)
    return bytes(out)


def _parse_tlv(data):
    res, i = {}, 0
    while i + 4 <= len(data):
        tag = data[i] | (data[i + 1] << 8)
        ln = data[i + 2] | (data[i + 3] << 8)
        val = data[i + 4:i + 4 + ln]
        i += 4 + ln
        res[tag] = val.decode("utf-8", errors="replace")
    return res


# ------------------------------------------------------------------ API

def spisak_citaca():
    try:
        return readers()
    except Exception:
        return []


def kartica_prisutna(citac):
    try:
        c = citac.createConnection()
        c.connect()
        atr = bytes(c.getATR())
        c.disconnect()
        return atr
    except (NoCardException, CardConnectionException):
        return None
    except Exception:
        return None


def _povezi(citac):
    """Ekskluzivna veza + reset kartice na kraju, da Windows (CertPropSvc)
    ne bi istovremeno pristupao kartici i menjao izabrani fajl."""
    conn = citac.createConnection()
    try:
        conn.connect(mode=SCARD_SHARE_EXCLUSIVE, disposition=SCARD_RESET_CARD)
    except NoCardException:
        raise CitacGreska("Kartica nije ubačena.")
    except (CardConnectionException, TypeError):
        conn = citac.createConnection()          # starija pyscard / zauzet čitač
        try:
            conn.connect()
        except (NoCardException, CardConnectionException):
            raise CitacGreska("Kartica nije ubačena ili je čitač zauzet.")
    return conn


def _procitaj_jednom(citac):
    conn = _povezi(citac)
    try:
        for aid in AIDS:                    # Gemalto / nove; Apollo nema AID
            if _select(conn, aid, 0x04, 0x00) or _select(conn, aid, 0x04):
                break
        sirovo = {}
        for f in (FILE_DOCUMENT, FILE_PERSONAL, FILE_RESIDENCE):
            sirovo.update(_parse_tlv(_read_file(conn, f)))
        return sirovo
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass


def procitaj(citac, pokusaja=4):
    greska = None
    for i in range(pokusaja):
        try:
            sirovo = _procitaj_jednom(citac)
            break
        except CitacGreska as ex:
            greska = ex
            if "nije ubačena" in str(ex) and "zauzet" not in str(ex):
                raise
        except Exception as ex:
            greska = CitacGreska(str(ex))
        time.sleep(0.8)
    else:
        raise greska
    lk = LicnaKarta(sirovo=sirovo)
    lk.polja = {naziv: sirovo.get(tag, "") for tag, naziv in TAGS.items()}
    if not lk.get("jmbg"):
        raise CitacGreska("Kartica je očitana, ali JMBG nije pronađen. "
                          "Pokrenite 'citac_lk.py --dump' radi provere.")
    return lk


if __name__ == "__main__":
    cit = spisak_citaca()
    if not cit:
        sys.exit("Nije pronađen nijedan čitač.")
    print("Čitač:", cit[0])
    lk = procitaj(cit[0])
    if "--dump" in sys.argv:
        for t, v in sorted(lk.sirovo.items()):
            print(f"  {t}: {TAGS.get(t, '?'):22s} {v}")
    print("Ime i prezime:", lk.ime_prezime)
    print("JMBG:", lk.get("jmbg"), "(ispravan)" if jmbg_ispravan(lk.get("jmbg")) else "(NEISPRAVAN)")
    print("Datum rođenja:", lk.datum_rodjenja)
    print("Mesto:", lk.mesto)
    print("Adresa:", lk.ulica_broj)
    print("Dokument:", lk.dokument)
