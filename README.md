# Izjava birača – popunjavanje sa lične karte

Program očita ličnu kartu sa čipom, popuni obrazac NENS-5 i pošalje ga direktno
na štampač. Podaci se nigde ne čuvaju: brišu se kad se kartica izvadi ili se klikne "Očisti".

## Pokretanje (Windows)
    pip install -r requirements.txt
    python main.py

Probni ispis bez kartice:  `python main.py --test`, zatim "Pregled".
Provera čitanja kartice:   `python citac_lk.py --dump`

## Pravljenje .exe
    pip install pyinstaller
    pyinstaller --onedir --windowed --name IzjavaBiraca --add-data "obrazac.pdf;." main.py

Pored `IzjavaBiraca.exe` iskopirajte `obrazac.pdf` i `config.ini`.

## Obrazac
`obrazac.pdf` je napravljen iz dostavljenog .doc fajla. Možete ga zameniti
PDF-om izvezenim iz Word-a (File → Save As → PDF, jedna strana). Program sam
pronalazi polja po oznakama "(име и презиме)", "(ЈМБГ)", "увидом у" itd.

## Podešavanje štampe (config.ini)
Ako tekst na papiru malo "beži" od crta, podesite `pomeraj_x_mm` / `pomeraj_y_mm`.
