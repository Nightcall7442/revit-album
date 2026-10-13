# -*- coding: utf-8 -*-
"""Full builds of every reference case (examples/* and cases/*): the album must come out with 0 errors and the
key numbers must not drift. Slow (about 1.5 min for the Urgench apartment) - part of the delivery gate."""
import json
import os

import pytest

from conftest import case_dirs


@pytest.mark.slow
@pytest.mark.parametrize("case", case_dirs(), ids=lambda d: os.path.basename(d))
def test_case_builds_clean(case, tmp_path):
    from sdalbum import album, qa, validate
    exp = json.load(open(os.path.join(case, "expected.json"), encoding="utf-8"))
    A = album.build(os.path.join(case, "project.json"), str(tmp_path), exp.get("sheets_keys"))
    A.save_dxf(str(tmp_path / "album.dxf"))
    rep = qa.check_doc(A.doc)
    e, w = qa.summary(rep)
    data = validate.run(A.P)
    build = A.issues + A.check_clipping()
    errs = [i for v in rep.values() for i in v if i["level"] == "error"] + \
           [i for i in data + build if i["level"] == "error"]
    assert errs == [], errs[:5]
    assert len(A.sheets) == exp["sheets"]
    assert A.plan_k == exp.get("plan_scale", A.plan_k)
    assert abs(A.P.total_area() - exp["total_area"]) < 0.01
    allowed = set(exp.get("accepted_data_warnings", []))
    unexpected = sorted({i["code"] for i in data if i["level"] == "warning"} - allowed)
    assert unexpected == [], "new data warnings: %s" % unexpected
    assert w <= exp.get("max_sheet_warnings", 40)
    titles = [t for _, _, t, *_ in A.sheets]
    for t in exp.get("titles", []):
        assert t in titles
    pdf = A.render_pdf(str(tmp_path / "album.pdf"))
    import pymupdf
    assert len(pymupdf.open(pdf)) == exp["sheets"]
