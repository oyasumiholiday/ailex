import unittest

try:
    import jwt
except ModuleNotFoundError as exc:
    if exc.name != "jwt":
        raise
    jwt = None


@unittest.skipIf(jwt is None, "install PyJWT from the optional mcp extra")
class DependencySecurityTest(unittest.TestCase):
    def test_pyjwt_preserves_verification_options(self) -> None:
        key = "synthetic-HS256-key-for-dependency-regression-tests-only"
        token = jwt.encode({"exp": 1}, key, algorithm="HS256")

        # GHSA-gvp8-978c-rx2q: an unverified decode must not disable later checks.
        for decode in (jwt.decode, jwt.decode_complete):
            with self.subTest(api=decode.__name__):
                options = {"verify_signature": False}
                decode(token, key, algorithms=["HS256"], options=options)
                self.assertEqual(options, {"verify_signature": False})

                options["verify_signature"] = True
                with self.assertRaises(jwt.ExpiredSignatureError):
                    decode(token, key, algorithms=["HS256"], options=options)
