import json
import logging
import sqlite3
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "db" / "pesquisa.db"
HOST = "127.0.0.1"
PORT = 8000
MAX_REQUEST_BYTES = 16_384
AGE_GROUPS = (
    "7 a 8 anos",
    "9 a 11 anos",
    "12 a 14 anos",
    "15 a 17 anos",
    "18 ou mais",
)
EDUCATION_LEVELS = {
    "Ensino Fundamental": tuple(f"Ano {year}" for year in range(1, 10)),
    "Ensino Médio": tuple(f"Ano {year}" for year in range(1, 4)),
}

def initialize_database():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS surveys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                school TEXT NOT NULL,
                grade TEXT NOT NULL,
                education_level TEXT CHECK (education_level IN ('Ensino Fundamental', 'Ensino Médio')),
                grade_year TEXT CHECK (grade_year IN ('Ano 1', 'Ano 2', 'Ano 3', 'Ano 4', 'Ano 5', 'Ano 6', 'Ano 7', 'Ano 8', 'Ano 9')),
                idade TEXT NOT NULL CHECK (idade IN ('7 a 8 anos', '9 a 11 anos', '12 a 14 anos', '15 a 17 anos', '18 ou mais')),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )
        survey_columns = {column[1] for column in connection.execute("PRAGMA table_info(surveys)").fetchall()}
        if "idade" not in survey_columns:
            connection.execute(
                "ALTER TABLE surveys ADD COLUMN idade TEXT NOT NULL DEFAULT '18 ou mais' "
                "CHECK (idade IN ('7 a 8 anos', '9 a 11 anos', '12 a 14 anos', '15 a 17 anos', '18 ou mais'))"
            )
        if "education_level" not in survey_columns:
            connection.execute(
                "ALTER TABLE surveys ADD COLUMN education_level TEXT "
                "CHECK (education_level IN ('Ensino Fundamental', 'Ensino Médio'))"
            )
        if "grade_year" not in survey_columns:
            connection.execute(
                "ALTER TABLE surveys ADD COLUMN grade_year TEXT "
                "CHECK (grade_year IN ('Ano 1', 'Ano 2', 'Ano 3', 'Ano 4', 'Ano 5', 'Ano 6', 'Ano 7', 'Ano 8', 'Ano 9'))"
            )
        for survey_id, grade in connection.execute(
            "SELECT id, grade FROM surveys WHERE education_level IS NULL OR grade_year IS NULL"
        ):
            education_level, separator, grade_year = grade.partition(" - ")
            if separator and grade_year in EDUCATION_LEVELS.get(education_level, ()):
                connection.execute(
                    "UPDATE surveys SET education_level = ?, grade_year = ? WHERE id = ?",
                    (education_level, grade_year, survey_id),
                )
        survey_columns = {
            column[1]: column
            for column in connection.execute("PRAGMA table_info(surveys)").fetchall()
        }
        if any(
            survey_columns.get(column) and survey_columns[column][3]
            for column in ("liked_game", "expo_xp_rating")
        ):
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute(
                """
                CREATE TABLE surveys_updated (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    school TEXT NOT NULL,
                    grade TEXT NOT NULL,
                    idade TEXT NOT NULL CHECK (idade IN ('7 a 8 anos', '9 a 11 anos', '12 a 14 anos', '15 a 17 anos', '18 ou mais')),
                    liked_game TEXT CHECK (liked_game IN ('S', 'N')),
                    expo_xp_rating INTEGER CHECK (expo_xp_rating BETWEEN 0 AND 10),
                    pontos INTEGER NOT NULL DEFAULT 0 CHECK (pontos BETWEEN 0 AND 999),
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    education_level TEXT CHECK (education_level IN ('Ensino Fundamental', 'Ensino Médio')),
                    grade_year TEXT CHECK (grade_year IN ('Ano 1', 'Ano 2', 'Ano 3', 'Ano 4', 'Ano 5', 'Ano 6', 'Ano 7', 'Ano 8', 'Ano 9'))
                )
                """
            )
            connection.execute(
                """
                INSERT INTO surveys_updated
                    (id, name, school, grade, idade, liked_game, expo_xp_rating, pontos, created_at, education_level, grade_year)
                SELECT id, name, school, grade, idade, liked_game, expo_xp_rating, pontos, created_at, education_level, grade_year
                FROM surveys
                """
            )
            connection.execute("DROP TABLE surveys")
            connection.execute("ALTER TABLE surveys_updated RENAME TO surveys")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS arcade_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER NOT NULL REFERENCES surveys(id),
                won INTEGER NOT NULL CHECK (won IN (0, 1)),
                targets_hit INTEGER NOT NULL CHECK (targets_hit BETWEEN 0 AND 80),
                targets_lost INTEGER NOT NULL CHECK (targets_lost BETWEEN 0 AND 80),
                people_rescued INTEGER NOT NULL CHECK (people_rescued BETWEEN 0 AND 20),
                mission_score INTEGER NOT NULL CHECK (mission_score >= 0),
                lives_remaining INTEGER NOT NULL CHECK (lives_remaining BETWEEN 0 AND 5),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )


class GameRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        if urlsplit(self.path).path == "/index.html":
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path == "/api/health":
            self._send_json(200, {"status": "ok"})
            return

        if path in ("", "/"):
            self.path = "/index.html"
        elif path.startswith("/img/"):
            requested_file = (ROOT / path.lstrip("/")).resolve()
            image_directory = (ROOT / "img").resolve()
            if requested_file.parent != image_directory or requested_file.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                self.send_error(404)
                return
        elif path.startswith("/mp3/"):
            requested_file = (ROOT / path.lstrip("/")).resolve()
            audio_directory = (ROOT / "mp3").resolve()
            if requested_file.parent != audio_directory or requested_file.suffix.lower() != ".mp3":
                self.send_error(404)
                return
        elif path != "/index.html":
            self.send_error(404)
            return

        super().do_GET()

    def do_OPTIONS(self):
        if urlsplit(self.path).path not in ("/api/survey", "/api/arcade-matches"):
            self.send_error(404)
            return

        origin = self.headers.get("Origin")
        if not self._is_local_origin(origin):
            self._send_json(403, {"error": "A origem da página não é permitida."})
            return

        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/api/survey", "/api/arcade-matches"):
            self.send_error(404)
            return

        origin = self.headers.get("Origin")
        if origin and not self._is_local_origin(origin):
            self._send_json(403, {"error": "A origem da página não é permitida."})
            return

        content_type = self.headers.get_content_type()
        if content_type != "application/json":
            self._send_json(415, {"error": "O formulário deve ser enviado em JSON."})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Tamanho da solicitação inválido."})
            return

        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(413, {"error": "Tamanho da solicitação inválido."})
            return

        try:
            payload = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "O formulário contém JSON inválido."})
            return

        if not isinstance(payload, dict):
            self._send_json(400, {"error": "Os dados do formulário são inválidos."})
            return

        if path == "/api/arcade-matches":
            self._save_arcade_match(payload)
            return

        text_fields = ("name", "school")
        values = {}
        for field in text_fields:
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120:
                self._send_json(400, {"error": "Preencha nome e escola (até 120 caracteres)."})
                return
            values[field] = value.strip()

        education_level = payload.get("education_level")
        grade_year = payload.get("grade_year")
        if (
            not isinstance(education_level, str)
            or not isinstance(grade_year, str)
            or grade_year not in EDUCATION_LEVELS.get(education_level, ())
        ):
            self._send_json(400, {"error": "Selecione um nível de ensino e ano válidos."})
            return

        age = payload.get("idade")
        if age not in AGE_GROUPS:
            self._send_json(400, {"error": "Selecione uma faixa etária válida."})
            return

        try:
            with sqlite3.connect(DATABASE) as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO surveys (name, school, grade, education_level, grade_year, idade)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        values["name"],
                        values["school"],
                        f"{education_level} - {grade_year}",
                        education_level,
                        grade_year,
                        age,
                    ),
                )
        except sqlite3.Error:
            logging.exception("Falha ao salvar resposta da pesquisa no SQLite.")
            self._send_json(500, {"error": "Não foi possível salvar a pesquisa. Tente novamente."})
            return

        self._send_json(
            201,
            {
                "id": cursor.lastrowid,
                "message": "Credencial salva com sucesso.",
            },
        )

    def _save_arcade_match(self, payload):
        player_id = payload.get("player_id")
        if isinstance(player_id, bool) or not isinstance(player_id, int) or player_id <= 0:
            self._send_json(400, {"error": "O cadastro do jogador é inválido."})
            return

        won = payload.get("won")
        if not isinstance(won, bool):
            self._send_json(400, {"error": "O resultado da partida é inválido."})
            return

        numeric_fields = {
            "targets_hit": (0, 80),
            "targets_lost": (0, 80),
            "people_rescued": (0, 20),
            "mission_score": (0, 1_000_000),
            "lives_remaining": (0, 5),
        }
        values = {}
        for field, (minimum, maximum) in numeric_fields.items():
            value = payload.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                self._send_json(400, {"error": "As informações da partida são inválidas."})
                return
            values[field] = value
        if values["targets_hit"] + values["targets_lost"] > 80:
            self._send_json(400, {"error": "A quantidade de alvos da partida é inválida."})
            return

        try:
            with sqlite3.connect(DATABASE) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                if connection.execute("SELECT 1 FROM surveys WHERE id = ?", (player_id,)).fetchone() is None:
                    self._send_json(404, {"error": "O cadastro do jogador não foi encontrado."})
                    return
                cursor = connection.execute(
                    """
                    INSERT INTO arcade_matches
                        (player_id, won, targets_hit, targets_lost, people_rescued, mission_score, lives_remaining)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        player_id,
                        int(won),
                        values["targets_hit"],
                        values["targets_lost"],
                        values["people_rescued"],
                        values["mission_score"],
                        values["lives_remaining"],
                    ),
                )
        except sqlite3.Error:
            logging.exception("Falha ao salvar o resultado da partida no SQLite.")
            self._send_json(500, {"error": "Não foi possível salvar as informações da partida. Tente novamente."})
            return

        self._send_json(201, {"id": cursor.lastrowid, "message": "Partida salva com sucesso."})

    @staticmethod
    def _is_local_origin(origin):
        if not origin:
            return False

        try:
            parsed_origin = urlsplit(origin)
            return (
                parsed_origin.scheme == "http"
                and parsed_origin.hostname in ("localhost", "127.0.0.1")
                and (parsed_origin.port is None or 1 <= parsed_origin.port <= 65535)
                and not parsed_origin.username
                and not parsed_origin.password
                and not parsed_origin.path
                and not parsed_origin.query
                and not parsed_origin.fragment
            )
        except ValueError:
            return False

    def _send_json(self, status, payload):
        response = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin")
        if self._is_local_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(response)


def main():
    initialize_database()
    server = ThreadingHTTPServer((HOST, PORT), GameRequestHandler)
    print(f"Jogo disponível em http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
