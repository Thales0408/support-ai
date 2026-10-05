import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import ai, audio


class AudioAiTest(unittest.TestCase):

    def test_custo_groq_respeita_modelo(self):

        with patch("services.ai.TRANSCRIBE_USD_HORA_GROQ", 0.04), \
                patch("services.ai.TRANSCRIBE_USD_HORA_GROQ_LARGE_V3", 0.111):

            self.assertAlmostEqual(
                ai.estimar_custo_transcricao(
                    3600,
                    "groq",
                    modelo="whisper-large-v3-turbo"
                ),
                0.04,
                places=4
            )
            self.assertAlmostEqual(
                ai.estimar_custo_transcricao(
                    3600,
                    "groq",
                    modelo="whisper-large-v3"
                ),
                0.111,
                places=4
            )

    def test_custo_openai_mini_respeita_modelo(self):

        with patch("services.ai.TRANSCRIBE_USD_MINUTO_OPENAI", 0.006), \
                patch("services.ai.TRANSCRIBE_USD_MINUTO_OPENAI_MINI", 0.003):

            self.assertAlmostEqual(
                ai.estimar_custo_transcricao(
                    60,
                    "openai",
                    modelo="gpt-4o-mini-transcribe"
                ),
                0.003,
                places=4
            )

    def test_audio_temporario_e_removido_por_padrao(self):

        with tempfile.TemporaryDirectory() as pasta:

            def fake_run(comando, **kwargs):

                Path(comando[-1]).write_bytes(b"wav-processado")

            with patch(
                "services.audio.AUDIO_DIAGNOSTICS_DIR",
                pasta
            ), patch(
                "services.audio.AUDIO_DIAGNOSTICS_KEEP",
                False
            ), patch(
                "services.audio.AUDIO_PREPROCESS_ENABLED",
                True
            ), patch(
                "services.audio.subprocess.run",
                side_effect=fake_run
            ):

                resultado = audio.preprocessar_audio_transcricao(
                    b"audio-original",
                    "chunk.webm"
                )

            self.assertTrue(resultado["audio_processado"])
            self.assertEqual(
                resultado["audio_bytes"],
                b"wav-processado"
            )
            self.assertEqual(
                resultado["audio_original_path"],
                ""
            )
            self.assertEqual(
                resultado["audio_processado_path"],
                ""
            )
            self.assertEqual(
                list(Path(pasta).iterdir()),
                []
            )


if __name__ == "__main__":

    unittest.main()
