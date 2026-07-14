"""
ZiggoGo EPG

XML TV structure writer
"""

import json
import logging
import sqlite3

from typing import List, Optional

from lxml import etree


class XMLTVWriter:
    """Write XMLTV data from database"""

    # Mapping of Ziggo genre names to the DVB (ETSI EN 300 468) category names known by TVHeadend.
    # Ziggo genres are free-form and hand-typed, so keys are lowercase and matched case-insensitively.
    GENRE_MAP = {
        # Movies
        "film": "Movie / Drama",
        "actie": "Adventure / Western / War",
        "avontuur": "Adventure / Western / War",
        "animatie": "Cartoons / Puppets",
        "anime": "Cartoons / Puppets",
        "komedie": "Comedy",
        "romantische komedie": "Comedy",
        "standup komedie": "Comedy",
        "zwarte komedie": "Comedy",
        "sitcoms": "Comedy",
        "documentaire": "Documentary",
        "docudrama": "Documentary",
        "docusoap": "Documentary",
        "drama": "Movie / Drama",
        "dramaseries": "Movie / Drama",
        "historisch drama": "Serious / Classical / Religious / Historical movie / Drama",
        "misdaaddrama": "Detective / Thriller",
        "miniseries": "Movie / Drama",
        "fantasy": "Science fiction / Fantasy / Horror",
        "sciencefiction": "Science fiction / Fantasy / Horror",
        "horror": "Science fiction / Fantasy / Horror",
        "thriller": "Detective / Thriller",
        "mysterie": "Detective / Thriller",
        "misdaad": "Detective / Thriller",
        "romantiek": "Romance",
        "western": "Adventure / Western / War",
        "oorlog": "Adventure / Western / War",
        "musical": "Musical / Opera",
        "biografie": "Documentary",
        # News and current affairs
        "nieuws": "News / Current affairs",
        "actualiteit": "News / Current affairs",
        "actualiteitenprogramma's": "News / Current affairs",
        "debat": "Discussion / Interview / Debate",
        "politiek": "Social / Political issues / Economics",
        "politieke satire": "Social / Political issues / Economics",
        "interview": "Discussion / Interview / Debate",
        "business & financial": "News / Current affairs",
        "weer": "News / Weather report",
        # Sports
        "sport": "Sports",
        "voetbal": "Football / Soccer",
        "american football": "Team sports (excluding football)",
        "basketbal": "Team sports (excluding football)",
        "tennis": "Tennis / Squash",
        "golf": "Sports",
        "atletiek": "Athletics",
        "wielrennen": "Sports",
        "motorsport": "Motor sport",
        "motorracen": "Motor sport",
        "rugby": "Team sports (excluding football)",
        "rugby league": "Team sports (excluding football)",
        "rugby union": "Team sports (excluding football)",
        "honkbal": "Team sports (excluding football)",
        "cricket": "Team sports (excluding football)",
        "volleybal": "Team sports (excluding football)",
        "darts": "Sports",
        "snooker": "Sports",
        "paardensport": "Equestrian",
        "zeilen": "Water sport",
        "skateboarden": "Sports",
        "extreme sporten": "Sports",
        "vliegsport": "Sports",
        "mixed martial arts (mma)": "Martial sports",
        "running": "Athletics",
        "stierenvechten": "Sports",
        "cheerleading": "Sports",
        "competitiesporten": "Sports",
        "multisportevenement": "Special events (Olympic Games, World Cup, etc.)",
        "sporttalkshow": "Sports magazines",
        "exercise": "Fitness and health",
        "outdoor": "Sports",
        "schermen": "Sports",
        # Children
        "kinderen": "Children's / Youth programs",
        "kids en familie": "Children's / Youth programs",
        # Music
        "muziek": "Music / Ballet / Dance",
        "ballet": "Ballet",
        "dans": "Music / Ballet / Dance",
        "opera": "Musical / Opera",
        "podiumkunsten": "Performing arts",
        "awards": "Music / Ballet / Dance",
        # Arts and culture
        "beeldende kunst": "Fine arts",
        "kunstnijverheid": "Handicraft",
        "boeken & literatuur": "Literature",
        "religie": "Religion",
        "geschiedenis": "Documentary",
        "bloemlezing": "Arts / Culture (without music)",
        # Social and political issues
        "samenleving": "Social / Political issues / Economics",
        "educatie": "Informational / Educational / School programs",
        "wetenschap": "Education / Science / Factual topics",
        "natuur": "Nature / Animals / Environment",
        "natuur en milieu": "Nature / Animals / Environment",
        "technologie": "Technology / Natural sciences",
        "dieren": "Nature / Animals / Environment",
        "gezondheid": "Medicine / Physiology / Psychology",
        "medisch": "Medicine / Physiology / Psychology",
        "opvoeden": "Informational / Educational / School programs",
        "lhbti": "Social / Political issues / Economics",
        "recht": "Social / Political issues / Economics",
        "paranormaal": "Detective / Thriller",
        "landbouw": "Nature / Animals / Environment",
        # Lifestyle
        "reizen": "Tourism / Travel",
        "culinair": "Cooking",
        "mode": "Fashion",
        "bouwen en verbouwen": "Leisure hobbies",
        "doe-het-zelf": "Leisure hobbies",
        "home & garden": "Gardening",
        "shoppen": "Advertisement / Shopping",
        "verzamelen": "Leisure hobbies",
        "veiling": "Advertisement / Shopping",
        "auto's": "Motoring",
        "motors": "Motoring",
        # Entertainment and shows
        "gamen": "Game show / Quiz / Contest",
        "entertainment": "Show / Game show",
        "cabaret": "Variety show",
        "variété": "Variety show",
        "spelshow": "Game show / Quiz / Contest",
        "talkshow": "Talk show",
        "reality": "Variety show",
        "reality-competitie": "Game show / Quiz / Contest",
        "event": "Show / Game show",
        "consumentenprogramma's": "Show / Game show",
        "soap": "Soap / Melodrama / Folkloric",
        "erotiek": "Adult movie / Drama",
        "erotisch": "Adult movie / Drama",
    }

    # Maps a DVB subcategory (lowercase) to its main category, so the main category can be dropped
    # when a more specific subcategory is present for the same programme.
    DVB_PRIORITY = {
        "detective / thriller": "Movie / Drama",
        "adventure / western / war": "Movie / Drama",
        "science fiction / fantasy / horror": "Movie / Drama",
        "comedy": "Movie / Drama",
        "soap / melodrama / folkloric": "Movie / Drama",
        "romance": "Movie / Drama",
        "serious / classical / religious / historical movie / drama": "Movie / Drama",
        "adult movie / drama": "Movie / Drama",
        "talk show": "Show / Game show",
        "game show / quiz / contest": "Show / Game show",
        "variety show": "Show / Game show",
        "football / soccer": "Sports",
        "team sports (excluding football)": "Sports",
        "tennis / squash": "Sports",
        "athletics": "Sports",
        "motor sport": "Sports",
        "water sport": "Sports",
        "equestrian": "Sports",
        "martial sports": "Sports",
        "sports magazines": "Sports",
        "fitness and health": "Sports",
        "special events (olympic games, world cup, etc.)": "Sports",
        "news / weather report": "News / Current affairs",
        "documentary": "News / Current affairs",
        "discussion / interview / debate": "News / Current affairs",
        "cartoons / puppets": "Children's / Youth programs",
        "ballet": "Music / Ballet / Dance",
        "rock / pop": "Music / Ballet / Dance",
        "musical / opera": "Music / Ballet / Dance",
        "performing arts": "Arts / Culture (without music)",
        "fine arts": "Arts / Culture (without music)",
        "religion": "Arts / Culture (without music)",
        "popular culture / traditional arts": "Arts / Culture (without music)",
        "literature": "Arts / Culture (without music)",
        "handicraft": "Leisure hobbies",
        "fashion": "Leisure hobbies",
        "motoring": "Leisure hobbies",
        "tourism / travel": "Leisure hobbies",
        "cooking": "Leisure hobbies",
        "gardening": "Leisure hobbies",
        "advertisement / shopping": "Leisure hobbies",
        "education / science / factual topics": "Social / Political issues / Economics",
        "nature / animals / environment": "Social / Political issues / Economics",
        "technology / natural sciences": "Social / Political issues / Economics",
        "medicine / physiology / psychology": "Social / Political issues / Economics",
        "economics / social advisory": "Social / Political issues / Economics",
        "remarkable people": "Social / Political issues / Economics",
        "informational / educational / school programs": "Social / Political issues / Economics",
        "magazines / reports / documentary": "Social / Political issues / Economics",
    }

    def __init__(self, database_connection: sqlite3.Connection, date_categories: Optional[List[str]] = None):
        """
        Initialize XMLTVWriter.

        :param database_connection: An opened SQLite database connection to the EPG data
        :param date_categories: Only include the production year for programmes that have one of these categories
                                (matched case-insensitively). If None, the production year is included for all programmes.
        """
        self._db = database_connection
        self._dbcur = self._db.cursor()
        self._date_categories = None
        if date_categories is not None:
            self._date_categories = {category.lower() for category in date_categories}

        # NL is hardcoded as it is the only language ZiggoGo provides.
        self._lang = "nl"

    def generate_xmltv(self) -> bytes:
        """
        Generate the XMLTV file from the database.
        :return: The XMLTV data as a string
        """

        logging.info("Generating XMLTV data...")

        xmltv = etree.Element(
            "tv",
            attrib={
                "source-info-url": "https://www.ziggogo.tv",
                "source-info-name": "ZiggoGo",
                "generator-info-name": "ZiggoGo EPG",
                "generator-info-url": "https://github.com/jbogers/ziggogo-epg",
            },
        )

        self._add_channels(xmltv=xmltv)
        self._add_programmes(xmltv=xmltv)

        return etree.tostring(xmltv, pretty_print=True)

    def _add_channels(self, xmltv: etree.Element):
        """Add the channels to the XMLTV element"""

        self._dbcur.execute("SELECT id, name, logo FROM channels")

        for row in self._dbcur:
            channel = etree.SubElement(xmltv, "channel", attrib={"id": row["id"].replace("_", ".")})
            etree.SubElement(channel, "display-name", attrib={"lang": self._lang}).text = row["name"]

            if row["logo"]:
                etree.SubElement(channel, "icon", attrib={"src": row["logo"]})

    def _add_programmes(self, xmltv: etree.Element):
        """Add the programmes to XMLTV element"""

        self._dbcur.execute(
            "SELECT channelid, title, starttime, endtime, pd.details AS details FROM programmes p "
            "LEFT JOIN programmedetails pd ON pd.id = p.id"
        )

        for row in self._dbcur:
            programme = etree.SubElement(
                xmltv,
                "programme",
                attrib={"start": row["starttime"], "stop": row["endtime"], "channel": row["channelid"].replace("_", ".")},
            )
            etree.SubElement(programme, "title", attrib={"lang": self._lang}).text = row["title"]

            if row["details"] is not None:
                details = json.loads(row["details"])

                if "sub-title" in details:
                    etree.SubElement(programme, "sub-title", attrib={"lang": self._lang}).text = details["sub-title"]

                if "desc" in details:
                    etree.SubElement(programme, "desc", attrib={"lang": self._lang}).text = details["desc"]

                if "credits" in details:
                    credits = etree.SubElement(programme, "credits")
                    if "directors" in details["credits"]:
                        for director in details["credits"]["directors"]:
                            etree.SubElement(credits, "director").text = director
                    if "actors" in details["credits"]:
                        for actor in details["credits"]["actors"]:
                            etree.SubElement(credits, "actor").text = actor
                    if "producers" in details["credits"]:
                        for producers in details["credits"]["producers"]:
                            etree.SubElement(credits, "producer").text = producers

                if "date" in details:
                    # The date (production year) of series episodes is often stale or generic upstream, causing
                    # TVHeadend to display incorrect years. Optionally limit the date to given categories (e.g. 'film').
                    if self._date_categories is None or not self._date_categories.isdisjoint(
                        category.lower() for category in details.get("categories", [])
                    ):
                        etree.SubElement(programme, "date").text = details["date"]

                if "categories" in details:
                    # Write the original categories, as they may be useful to other applications
                    for category in details["categories"]:
                        etree.SubElement(programme, "category", attrib={"lang": self._lang}).text = category

                    # Collect all matching DVB categories
                    dvb_codes = set()
                    for category in details["categories"]:
                        dvb_code = self.GENRE_MAP.get(category.lower())
                        if dvb_code:
                            dvb_codes.add(dvb_code)
                    # Remove main categories when a more specific subcategory is present
                    to_remove = set()
                    for code in dvb_codes:
                        parent = self.DVB_PRIORITY.get(code.lower())
                        if parent in dvb_codes:
                            to_remove.add(parent)
                    dvb_codes -= to_remove
                    # Additionally write a single DVB category (writing more than one makes
                    # TVHeadend accumulate categories over repeated EPG updates)
                    if dvb_codes:
                        etree.SubElement(programme, "category", attrib={"lang": "en"}).text = sorted(dvb_codes)[0]

                if "img" in details:
                    etree.SubElement(programme, "icon", attrib={"src": details["img"]})

                if "country" in details:
                    etree.SubElement(programme, "country").text = details["country"]

                if "episode" in details:
                    season = ""
                    ziggo_internal_id = False
                    try:
                        season = int(details["episode"]["season"]) - 1
                        if season >= 99999:
                            # Fake season number used in ZiggoGo that should never be displayed
                            ziggo_internal_id = True
                    except (KeyError, ValueError):
                        # No season value or not an integer
                        pass
                    episode = ""
                    try:
                        episode = int(details["episode"]["episode"]) - 1
                        if episode >= 9999999:
                            # Fake episode number used in ZiggoGo that should never be displayed
                            ziggo_internal_id = True
                    except (KeyError, ValueError):
                        # No season value or not an integer
                        pass
                    if not ziggo_internal_id and (season != "" or episode != ""):
                        etree.SubElement(programme, "episode-num", attrib={"system": "xmltv_ns"}).text = f"{season}.{episode}."

                if "rating" in details:
                    rating = etree.SubElement(programme, "rating", attrib={"system": "Kijkwijzer"})
                    etree.SubElement(rating, "value").text = details["rating"]

    def __del__(self):
        """Cleanup"""
        self._dbcur.close()
