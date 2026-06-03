"""T-OSN-W7-OSN-CLI-02 — Makefile absence invariant regression guard."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_makefile_does_not_exist():
    assert not (PROJECT_ROOT / "Makefile").exists(), (
        "Makefile was re-added. T-OSN-W7-GEMINI-02 R1~R5 의 5 라운드 RCE 패턴이 "
        "재발하지 않도록 Makefile 인터페이스는 영구 폐기됨. "
        "사용자는 bin/osn <subcommand> 사용. 추가 필요 시 새 ticket + threat model 검토."
    )


def test_no_makefile_variants():
    """Makefile.* 변형도 차단 (Makefile.deprecated, GNUmakefile 등).

    Note: macOS/Windows 의 case-insensitive FS 에서는 'Makefile' 과 'makefile' 이
    같은 inode 를 가리킨다. 'makefile' / 'MAKEFILE' 변형 검사는 case-strict FS
    (Linux ext4 등) 에서만 독립적 의미가 있음.
    이 테스트는 정확한 inode 일치가 아닌 os.listdir() 기반 정확한 파일명 검사를 수행한다.
    """
    import os
    existing_names = set(os.listdir(PROJECT_ROOT))
    for variant in ["Makefile", "makefile", "GNUmakefile", "BSDmakefile", "Makefile.in", "Makefile.am"]:
        assert variant not in existing_names, (
            f"{variant} 도 폐기 대상 — os.listdir() 기반 정확한 파일명 검사"
        )
