"""부동산 시장 모니터링 탭 — 지도 / 지표 / 거래.

수도권(서울 25개 자치구 + 경기 23개 시) 주간 매매·전세 등락, 거래량, 전세가율을
실제 비율 지도(choropleth)로 보여주고, 시장지표·특이거래를 함께 본다.
(경기 외곽 8개 시군 연천·포천·동두천·양주·가평·양평·여주·파주는 제외. 서울·경기 경계는 굵은 선.)

설계 원칙(증시 탭과 동일 — 뷰어 / 데이터 계층 분리):
  - 이 모듈은 '뷰어'다. 지도 경계(SVG path)는 모듈 내 _GEO 상수에 들어 있다.
    (수도권 행정경계를 실제 비율로 미리 투영한 좌표. 외부 GeoJSON을 런타임에 받지
     않으므로 클라우드/해외 IP 차단 이슈가 없다.)
  - 지표 값은 fetch_*()가 돌려주는 dict를 받아 그린다. 실제 수집
    (engine/realestate_*.py — 국토부 실거래·부동산원 R-ONE·KOSIS)이 붙기 전에는
    _GEO에 내장된 샘플 수치로 렌더된다. fetch가 None/예외여도 화면이 비지 않는다.

렌더 방식:
  - 지도: 호버 인터랙션(JS) 때문에 components.html(iframe)로 렌더한다.
    iframe은 부모 CSS 변수를 못 읽으므로 색을 hex로 인라인한다(파스텔 톤).
    한글 라벨 가독성을 위해 iframe 안에 Pretendard 웹폰트를 직접 임베드한다
    (실패 시 시스템 폰트 폴백). 라벨이 작은/생략된 구는 호버 시 큰 라벨로 보강.
  - 지표·거래: st.markdown으로 부모 문서에 그려 전역 변수(--sage 등)를 그대로 쓴다.

TODO(다음 단계):
  - fetch_region_metrics(): 부동산원 주간 시군구 지수 + 국토부 실거래 집계
  - fetch_indicators() / fetch_anomalies(): 실제 수집 연결
  - 거래 탭 필터 칩 동작(현재 정적)
  - 서울 확대/인셋(라벨 더 키우기) — mockup 승인 후 별도 적용
"""

import copy
import json

import streamlit as st
import streamlit.components.v1 as components

from modules.ui import foot_row   # 각주 배지(A안) — 정적 범례를 ⓘ 접힘 각주로 승격

_VIEWBOX = "0 0 1100 1087"

# ── 수도권 행정경계(실제 비율) + 내장 샘플 수치 ──────────────────
#   n(정식명) sl(짧은라벨) sd(seoul|gg) d(SVG path) cx,cy(라벨좌표) ar(라벨우선순위 면적)
#   mm/js/v/vc/jr (주간 매매%/전세%/거래건/거래전주비%/전세가율%)
_GEO = json.loads(r"""[{"n":"광주시","sl":"광주","sd":"gg","d":"M770.4 478.8L788.4 461.8L824.8 465.8L840.6 490.3L847.9 516.4L833.0 534.6L875.6 599.9L900.1 602.2L899.5 629.5L846.5 667.2L836.3 665.5L801.9 696.6L800.6 713.4L782.0 709.2L746.1 715.1L742.0 676.1L747.7 642.0L730.1 644.5L695.5 629.1L676.1 655.8L660.2 640.2L612.7 650.6L607.4 647.5L605.1 629.5L623.3 624.6L643.6 584.7L662.3 566.9L664.3 548.0L650.1 519.9L683.2 511.3L703.3 518.1L724.0 504.4L719.0 491.3L770.4 478.8Z","cx":755.2,"cy":592.3,"ar":74724,"mm":0.03,"js":0.06,"v":30,"vc":22,"jr":62},{"n":"화성시","sl":"화성","sd":"gg","d":"M408.0 705.5L409.5 720.0L429.8 727.9L451.3 753.3L498.9 756.9L515.1 739.2L540.9 742.4L562.2 765.1L622.0 763.0L630.6 799.3L603.8 810.9L594.4 833.7L576.2 834.6L566.9 819.4L547.9 815.3L538.8 781.9L503.2 780.0L477.1 802.1L504.1 815.9L511.0 841.6L480.9 850.4L476.3 883.2L462.6 903.2L430.3 906.4L420.4 913.6L382.6 904.7L365.2 913.6L341.1 947.8L322.7 958.6L283.5 960.1L276.0 943.8L239.6 943.7L237.1 924.8L249.5 906.6L258.0 873.5L247.2 866.1L256.6 849.5L281.6 848.5L290.7 827.0L277.2 804.3L265.4 814.4L235.4 813.7L217.8 839.2L180.0 860.8L165.3 840.0L174.3 829.5L153.4 816.9L158.7 772.5L169.4 758.2L157.1 745.6L178.3 720.9L223.4 732.7L245.4 728.2L276.3 738.4L277.0 716.5L296.4 703.9L328.7 716.6L395.1 693.4L408.0 705.5Z","cx":397.3,"cy":823.2,"ar":127269,"mm":0.12,"js":-0.01,"v":63,"vc":-4,"jr":65},{"n":"김포시","sl":"김포","sd":"gg","d":"M176.5 279.1L163.6 326.0L291.1 395.1L280.4 416.5L232.6 405.3L215.0 406.6L189.7 382.3L150.0 362.7L130.2 372.4L122.0 392.4L69.4 410.6L27.7 348.4L22.0 325.9L26.1 300.5L17.8 291.4L24.9 267.2L14.0 239.6L52.7 237.7L63.8 250.1L104.6 253.0L132.7 228.7L159.5 222.9L176.5 279.1Z","cx":95.6,"cy":313.2,"ar":53647,"mm":-0.02,"js":0.11,"v":45,"vc":-3,"jr":57},{"n":"안성시","sl":"안성","sd":"gg","d":"M959.0 914.0L914.1 930.0L914.4 952.0L903.6 961.1L887.4 969.8L853.3 973.6L844.6 986.5L860.8 1002.4L838.5 1017.9L811.0 1016.9L772.3 1039.3L753.8 1072.9L735.1 1054.4L710.2 1050.4L687.4 1038.1L670.0 1017.3L615.0 998.8L591.3 1001.1L606.8 978.0L623.2 973.8L616.0 955.7L623.4 943.5L577.8 937.5L598.8 921.5L594.7 884.4L663.6 886.6L702.5 855.7L716.8 854.2L716.1 833.1L752.2 846.3L773.7 871.0L789.1 857.6L805.0 872.3L819.1 869.2L858.2 880.6L882.1 876.5L879.0 851.3L887.5 830.6L957.3 858.8L969.9 887.7L959.0 914.0Z","cx":767.6,"cy":947.7,"ar":95006,"mm":-0.0,"js":0.04,"v":22,"vc":-1,"jr":66},{"n":"이천시","sl":"이천","sd":"gg","d":"M899.5 629.5L926.3 626.6L944.5 644.9L967.4 647.7L998.7 683.9L982.1 710.1L990.1 736.2L978.8 742.1L984.3 780.7L971.1 795.3L980.0 806.1L1008.1 803.0L1027.3 791.1L1047.7 791.9L1086.0 837.0L1079.6 879.7L1050.7 890.0L1017.6 911.5L1004.8 929.3L983.8 918.3L944.9 921.2L959.0 914.0L969.9 887.7L957.3 858.8L870.8 823.6L872.5 806.4L842.2 797.2L838.2 785.0L809.7 776.5L792.0 760.1L801.9 696.6L836.3 665.5L846.5 667.2L899.5 629.5Z","cx":900.4,"cy":778.6,"ar":88994,"mm":0.01,"js":0.0,"v":36,"vc":-21,"jr":61},{"n":"용인시","sl":"용인","sd":"gg","d":"M792.0 760.1L809.7 776.5L838.2 785.0L842.2 797.2L872.5 806.4L870.8 823.6L887.5 830.6L879.0 851.3L882.1 876.5L858.2 880.6L819.1 869.2L805.0 872.3L789.1 857.6L773.7 871.0L752.2 846.3L716.1 833.1L716.8 854.2L702.5 855.7L663.6 886.6L594.7 884.4L581.4 850.7L603.8 810.9L630.6 799.3L622.0 763.0L562.2 765.1L540.9 742.4L558.1 726.7L539.4 712.5L562.2 697.6L563.1 686.8L535.1 688.5L535.4 676.8L515.4 664.9L509.2 642.6L495.2 636.1L503.9 616.4L588.8 653.4L660.2 640.2L676.1 655.8L695.5 629.1L730.1 644.5L747.7 642.0L742.0 676.1L746.1 715.1L782.0 709.2L800.6 713.4L792.0 760.1Z","cx":671.4,"cy":751.3,"ar":105999,"mm":0.31,"js":0.11,"v":116,"vc":27,"jr":52},{"n":"하남시","sl":"하남","sd":"gg","d":"M634.5 418.5L667.5 407.4L700.8 439.3L701.3 447.5L743.5 469.2L751.7 481.5L719.0 491.3L724.0 504.4L703.3 518.1L683.2 511.3L645.2 520.9L610.8 519.5L631.3 494.2L615.3 478.2L633.0 451.4L650.9 436.2L634.5 418.5Z","cx":676.7,"cy":460.3,"ar":15992,"mm":0.26,"js":0.26,"v":48,"vc":4,"jr":51},{"n":"의왕시","sl":"의왕","sd":"gg","d":"M517.1 574.9L519.0 585.8L495.2 636.1L459.1 659.9L443.2 682.7L413.3 682.4L410.9 678.5L426.5 662.5L460.6 589.2L490.0 576.7L517.1 574.9Z","cx":478.0,"cy":612.6,"ar":11653,"mm":0.05,"js":0.07,"v":23,"vc":2,"jr":58},{"n":"군포시","sl":"군포","sd":"gg","d":"M441.1 626.5L426.5 662.5L410.9 678.5L388.7 664.7L360.9 666.6L379.2 629.9L395.5 613.4L420.8 609.8L441.1 626.5Z","cx":402.1,"cy":646.2,"ar":5510,"mm":0.14,"js":0.0,"v":16,"vc":-11,"jr":59},{"n":"시흥시","sl":"시흥","sd":"gg","d":"M265.6 521.3L311.2 533.2L330.6 577.9L341.3 588.5L359.9 587.9L364.6 612.5L348.3 626.6L309.0 625.0L275.9 647.3L249.7 645.7L212.7 672.5L183.8 652.9L191.8 632.9L241.8 568.2L256.8 563.8L265.7 541.4L265.6 521.3Z","cx":289.6,"cy":600.5,"ar":27337,"mm":0.04,"js":0.01,"v":19,"vc":-4,"jr":59},{"n":"오산시","sl":"오산","sd":"gg","d":"M576.2 834.6L562.4 845.9L516.3 848.4L504.1 815.9L477.1 802.1L503.2 780.0L538.8 781.9L547.9 815.3L566.9 819.4L576.2 834.6Z","cx":518.0,"cy":808.7,"ar":6778,"mm":0.03,"js":0.06,"v":30,"vc":-10,"jr":60},{"n":"남양주시","sl":"남양주","sd":"gg","d":"M731.6 226.8L781.3 239.4L804.5 275.4L816.5 280.9L814.6 299.9L839.2 327.8L831.5 353.0L813.4 372.4L803.2 406.8L771.1 458.1L770.4 478.8L751.7 481.5L743.5 469.2L701.3 447.5L700.8 439.3L667.5 407.4L634.5 418.5L614.2 379.3L620.7 361.3L583.4 358.5L565.4 351.3L567.9 313.9L555.3 307.0L597.3 277.3L599.9 257.9L617.3 251.2L642.5 251.3L652.5 241.8L680.5 244.8L692.1 252.5L725.2 238.2L731.6 226.8Z","cx":702.7,"cy":355.7,"ar":72309,"mm":-0.02,"js":0.04,"v":56,"vc":18,"jr":64},{"n":"구리시","sl":"구리","sd":"gg","d":"M583.4 358.5L620.7 361.3L614.2 379.3L634.5 418.5L585.2 436.8L573.6 424.2L589.9 394.6L578.2 379.1L583.4 358.5Z","cx":605.8,"cy":406.6,"ar":4768,"mm":0.15,"js":0.06,"v":16,"vc":15,"jr":60},{"n":"과천시","sl":"과천","sd":"gg","d":"M466.4 534.4L512.3 535.8L522.6 560.4L517.1 574.9L490.0 576.7L460.6 589.2L440.4 565.3L442.1 550.7L466.4 534.4Z","cx":481.1,"cy":562.8,"ar":4505,"mm":0.31,"js":0.27,"v":42,"vc":34,"jr":58},{"n":"고양시","sl":"고양","sd":"gg","d":"M340.3 270.5L365.9 284.6L383.9 276.4L390.2 258.7L410.2 257.2L403.4 273.1L401.7 330.4L419.8 331.4L424.6 317.7L444.1 310.7L469.4 323.1L457.9 346.6L462.6 364.1L450.4 368.2L433.7 346.2L393.7 356.7L382.7 386.8L383.6 403.7L364.9 407.6L341.5 423.2L163.6 326.0L168.6 303.4L183.0 312.9L214.9 299.3L261.9 299.1L282.2 271.5L300.0 281.1L340.3 270.5Z","cx":324.4,"cy":338.8,"ar":50763,"mm":-0.03,"js":-0.02,"v":53,"vc":5,"jr":57},{"n":"안산시","sl":"안산","sd":"gg","d":"M67.1 704.5L92.5 721.1L103.9 720.6L117.1 745.8L143.5 756.4L140.2 770.4L81.4 761.1L65.5 776.6L42.5 774.7L39.9 756.7L57.8 740.4L60.2 727.1L46.5 704.4L64.7 703.1L75.5 689.1L103.2 676.7L67.1 704.5ZM364.6 612.5L379.2 629.9L360.9 666.6L388.7 664.7L410.9 678.5L408.0 705.5L395.1 693.4L328.7 716.6L302.0 687.2L260.2 695.4L215.4 683.1L212.7 672.5L249.7 645.7L275.9 647.3L309.0 625.0L348.3 626.6L364.6 612.5Z","cx":300.8,"cy":656.0,"ar":20633,"mm":0.16,"js":-0.02,"v":61,"vc":-13,"jr":66},{"n":"평택시","sl":"평택","sd":"gg","d":"M576.2 834.6L594.4 833.7L581.4 850.7L594.7 884.4L598.8 921.5L577.8 937.5L623.4 943.5L616.0 955.7L623.2 973.8L606.8 978.0L591.3 1001.1L585.5 997.7L547.8 1030.4L507.6 1040.0L472.9 1033.1L390.2 1062.3L386.1 1042.2L369.4 1032.6L347.7 1035.8L346.0 1020.4L330.6 1010.3L310.6 983.9L279.0 966.6L283.5 960.1L322.7 958.6L341.1 947.8L365.2 913.6L382.6 904.7L420.4 913.6L430.3 906.4L462.6 903.2L476.3 883.2L480.9 850.4L511.0 841.6L516.3 848.4L562.4 845.9L576.2 834.6Z","cx":476.4,"cy":951.7,"ar":78730,"mm":0.1,"js":-0.01,"v":57,"vc":7,"jr":56},{"n":"광명시","sl":"광명","sd":"gg","d":"M318.3 516.5L329.9 519.0L357.7 508.4L382.3 554.2L359.9 587.9L341.3 588.5L330.6 577.9L311.2 533.2L318.3 516.5Z","cx":346.2,"cy":543.7,"ar":5695,"mm":0.31,"js":0.26,"v":93,"vc":-3,"jr":55},{"n":"부천시","sl":"부천","sd":"gg","d":"M318.3 516.5L311.2 533.2L255.6 521.4L231.5 505.4L234.0 481.0L248.5 477.3L255.6 442.7L258.9 447.9L307.5 455.6L306.0 503.3L318.3 516.5Z","cx":269.6,"cy":492.1,"ar":7855,"mm":0.07,"js":0.06,"v":62,"vc":9,"jr":64},{"n":"안양시","sl":"안양","sd":"gg","d":"M442.1 550.7L440.4 565.3L460.6 589.2L441.1 626.5L420.8 609.8L395.5 613.4L379.2 629.9L364.6 612.5L359.9 587.9L382.3 554.2L409.3 541.9L427.6 552.7L442.1 550.7Z","cx":408.7,"cy":576.6,"ar":8862,"mm":0.1,"js":0.07,"v":51,"vc":36,"jr":49},{"n":"의정부시","sl":"의정부","sd":"gg","d":"M576.9 227.5L610.6 242.4L617.3 251.2L599.9 257.9L597.3 277.3L555.3 307.0L525.7 315.9L492.4 302.6L489.4 279.1L479.4 264.7L479.5 243.6L495.1 238.1L525.8 245.4L576.9 227.5Z","cx":541.0,"cy":271.0,"ar":12190,"mm":0.16,"js":0.1,"v":56,"vc":9,"jr":66},{"n":"성남시","sl":"성남","sd":"gg","d":"M623.3 624.6L605.1 629.5L607.4 647.5L588.8 653.4L503.9 616.4L519.0 585.8L522.6 560.4L540.0 562.2L561.6 546.2L569.2 531.2L610.8 519.5L650.1 519.9L664.3 548.0L662.3 566.9L643.6 584.7L623.3 624.6Z","cx":573.3,"cy":601.1,"ar":21478,"mm":0.31,"js":0.16,"v":99,"vc":30,"jr":49},{"n":"수원시","sl":"수원","sd":"gg","d":"M498.9 756.9L451.3 753.3L429.8 727.9L409.5 720.0L408.0 705.5L413.3 682.4L443.2 682.7L459.1 659.9L495.2 636.1L509.2 642.6L515.4 664.9L535.4 676.8L535.1 688.5L563.1 686.8L562.2 697.6L539.4 712.5L558.1 726.7L540.9 742.4L515.1 739.2L498.9 756.9Z","cx":486.7,"cy":693.1,"ar":18736,"mm":0.26,"js":0.17,"v":79,"vc":34,"jr":49},{"n":"강동구","sl":"강동","sd":"seoul","d":"M585.2 436.8L634.5 418.5L650.9 436.2L633.0 451.4L615.3 478.2L591.0 467.6L581.8 452.9L585.2 436.8Z","cx":612.7,"cy":444.1,"ar":4125,"mm":0.24,"js":0.18,"v":99,"vc":24,"jr":56},{"n":"송파구","sl":"송파","sd":"seoul","d":"M541.2 470.5L571.5 468.0L581.8 452.9L591.0 467.6L615.3 478.2L631.3 494.2L610.8 519.5L594.0 527.6L581.4 505.4L543.9 489.6L541.2 470.5Z","cx":589.2,"cy":491.9,"ar":6730,"mm":0.36,"js":0.09,"v":105,"vc":26,"jr":58},{"n":"강남구","sl":"강남","sd":"seoul","d":"M497.2 460.9L541.2 470.5L543.9 489.6L581.4 505.4L594.0 527.6L569.2 531.2L557.7 517.8L528.6 524.3L509.8 509.1L488.6 467.8L497.2 460.9Z","cx":533.2,"cy":497.5,"ar":7410,"mm":0.28,"js":0.09,"v":97,"vc":15,"jr":50},{"n":"서초구","sl":"서초","sd":"seoul","d":"M488.6 467.8L509.8 509.1L528.6 524.3L557.7 517.8L569.2 531.2L561.6 546.2L540.0 562.2L522.6 560.4L512.3 535.8L466.4 534.4L459.7 516.7L458.3 482.8L488.6 467.8Z","cx":487.0,"cy":512.9,"ar":10469,"mm":0.13,"js":0.24,"v":128,"vc":36,"jr":48},{"n":"관악구","sl":"관악","sd":"seoul","d":"M459.7 516.7L466.4 534.4L442.1 550.7L427.6 552.7L395.9 534.8L381.3 513.2L384.9 508.7L426.8 500.1L449.1 517.9L459.7 516.7Z","cx":426.7,"cy":526.1,"ar":4476,"mm":-0.02,"js":-0.02,"v":38,"vc":-2,"jr":71},{"n":"동작구","sl":"동작","sd":"seoul","d":"M458.3 482.8L459.7 516.7L449.1 517.9L426.8 500.1L384.9 508.7L400.6 496.6L406.7 479.0L429.9 475.3L458.3 482.8Z","cx":430.8,"cy":489.7,"ar":3186,"mm":0.08,"js":-0.01,"v":15,"vc":18,"jr":56},{"n":"영등포구","sl":"영등포","sd":"seoul","d":"M372.1 446.5L423.4 466.3L429.9 475.3L406.7 479.0L400.6 496.6L384.9 508.7L376.0 487.3L362.3 478.4L372.1 446.5Z","cx":391.5,"cy":476.8,"ar":4205,"mm":0.12,"js":0.09,"v":70,"vc":34,"jr":48},{"n":"금천구","sl":"금천","sd":"seoul","d":"M381.3 513.2L395.9 534.8L409.3 541.9L382.3 554.2L357.7 508.4L381.3 513.2Z","cx":377.3,"cy":524.0,"ar":2363,"mm":0.0,"js":-0.03,"v":22,"vc":-6,"jr":63},{"n":"구로구","sl":"구로","sd":"seoul","d":"M310.1 486.5L362.3 478.4L376.0 487.3L384.9 508.7L381.3 513.2L357.7 508.4L329.9 519.0L318.3 516.5L306.0 503.3L310.1 486.5Z","cx":343.6,"cy":495.3,"ar":3203,"mm":-0.02,"js":-0.01,"v":15,"vc":-8,"jr":70},{"n":"강서구","sl":"강서","sd":"seoul","d":"M280.4 416.5L291.1 395.1L305.9 407.7L341.5 423.2L372.1 446.5L368.6 452.8L347.8 445.4L347.5 466.0L325.0 469.1L307.5 455.6L258.9 447.9L255.6 442.7L280.4 416.5Z","cx":309.6,"cy":432.9,"ar":8621,"mm":0.01,"js":0.12,"v":24,"vc":1,"jr":60},{"n":"양천구","sl":"양천","sd":"seoul","d":"M307.5 455.6L325.0 469.1L347.5 466.0L347.8 445.4L368.6 452.8L362.3 478.4L310.1 486.5L307.5 455.6Z","cx":357.1,"cy":460.8,"ar":2511,"mm":0.33,"js":0.17,"v":43,"vc":0,"jr":57},{"n":"마포구","sl":"마포","sd":"seoul","d":"M364.9 407.6L417.0 441.8L440.5 438.2L441.4 445.3L423.4 466.3L372.1 446.5L341.5 423.2L364.9 407.6Z","cx":375.7,"cy":430.7,"ar":5864,"mm":0.33,"js":0.14,"v":77,"vc":20,"jr":49},{"n":"서대문구","sl":"서대문","sd":"seoul","d":"M429.9 391.5L433.0 419.1L445.4 431.5L440.5 438.2L417.0 441.8L384.8 421.0L429.9 391.5Z","cx":420.1,"cy":405.3,"ar":3048,"mm":0.15,"js":0.1,"v":14,"vc":-2,"jr":58},{"n":"은평구","sl":"은평","sd":"seoul","d":"M450.4 368.2L431.6 375.3L429.9 391.5L384.8 421.0L364.9 407.6L383.6 403.7L382.7 386.8L393.7 356.7L433.7 346.2L450.4 368.2Z","cx":407.9,"cy":381.0,"ar":6395,"mm":0.14,"js":-0.02,"v":62,"vc":10,"jr":61},{"n":"노원구","sl":"노원","sd":"seoul","d":"M555.3 307.0L567.9 313.9L565.4 351.3L583.4 358.5L578.2 379.1L545.4 384.1L516.9 369.1L530.6 355.1L525.7 315.9L555.3 307.0Z","cx":547.3,"cy":333.6,"ar":5127,"mm":-0.03,"js":0.06,"v":48,"vc":6,"jr":56},{"n":"도봉구","sl":"도봉","sd":"seoul","d":"M525.7 315.9L530.6 355.1L516.9 369.1L489.3 349.1L495.0 332.2L485.2 318.2L492.4 302.6L525.7 315.9Z","cx":510.5,"cy":340.7,"ar":3019,"mm":-0.06,"js":-0.07,"v":36,"vc":2,"jr":61},{"n":"강북구","sl":"강북","sd":"seoul","d":"M469.4 323.1L485.2 318.2L495.0 332.2L489.3 349.1L525.0 375.7L512.4 387.0L487.5 383.3L462.6 364.1L457.9 346.6L469.4 323.1Z","cx":480.0,"cy":356.6,"ar":4616,"mm":-0.08,"js":0.01,"v":10,"vc":-21,"jr":67},{"n":"성북구","sl":"성북","sd":"seoul","d":"M453.5 369.0L462.6 364.1L487.5 383.3L512.4 387.0L525.0 375.7L545.4 384.1L545.7 392.5L516.0 403.6L499.4 419.9L469.1 407.2L464.6 385.0L453.5 369.0Z","cx":505.6,"cy":389.8,"ar":5145,"mm":0.12,"js":-0.0,"v":38,"vc":13,"jr":63},{"n":"중랑구","sl":"중랑","sd":"seoul","d":"M545.4 384.1L578.2 379.1L589.9 394.6L573.6 424.2L552.3 425.8L545.4 384.1Z","cx":565.7,"cy":409.4,"ar":2078,"mm":-0.08,"js":0.02,"v":18,"vc":-9,"jr":70},{"n":"동대문구","sl":"동대문","sd":"seoul","d":"M499.4 419.9L516.0 403.6L545.7 392.5L552.3 425.8L546.1 437.1L523.0 427.2L499.6 425.9L499.4 419.9Z","cx":528.6,"cy":411.7,"ar":2359,"mm":0.03,"js":0.03,"v":41,"vc":-15,"jr":59},{"n":"광진구","sl":"광진","sd":"seoul","d":"M552.3 425.8L573.6 424.2L585.2 436.8L581.8 452.9L571.5 468.0L541.2 470.5L531.3 466.6L552.3 425.8Z","cx":563.0,"cy":444.9,"ar":2496,"mm":0.36,"js":0.27,"v":115,"vc":15,"jr":48},{"n":"성동구","sl":"성동","sd":"seoul","d":"M499.6 425.9L523.0 427.2L546.1 437.1L531.3 466.6L497.2 460.9L485.5 452.4L499.6 425.9Z","cx":515.9,"cy":444.8,"ar":2466,"mm":0.16,"js":0.14,"v":117,"vc":37,"jr":57},{"n":"용산구","sl":"용산","sd":"seoul","d":"M463.4 443.1L497.2 460.9L458.3 482.8L429.9 475.3L423.4 466.3L441.4 445.3L463.4 443.1Z","cx":459.1,"cy":463.6,"ar":2930,"mm":0.13,"js":0.28,"v":67,"vc":24,"jr":52},{"n":"중구","sl":"중","sd":"seoul","d":"M499.6 425.9L485.5 452.4L463.4 443.1L441.4 445.3L445.4 431.5L499.6 425.9Z","cx":468.6,"cy":437.3,"ar":1542,"mm":-0.05,"js":0.06,"v":51,"vc":9,"jr":56},{"n":"종로구","sl":"종로","sd":"seoul","d":"M450.4 368.2L464.6 385.0L469.1 407.2L499.4 419.9L499.6 425.9L445.4 431.5L433.0 419.1L431.6 375.3L450.4 368.2Z","cx":449.5,"cy":396.1,"ar":4304,"mm":-0.03,"js":0.0,"v":45,"vc":-15,"jr":64}]""")

# 서울·경기 경계선(서울 외곽 윤곽) SVG path
_BORDER = r"""M318.3 516.5L306.0 503.3L310.1 486.5L307.5 455.6L258.9 447.9L255.6 442.7L280.4 416.5L291.1 395.1L305.9 407.7L341.5 423.2L364.9 407.6L383.6 403.7L382.7 386.8L393.7 356.7L433.7 346.2L450.4 368.2L464.6 385.0L453.5 369.0L462.6 364.1L457.9 346.6L469.4 323.1L485.2 318.2L492.4 302.6L525.7 315.9L555.3 307.0L567.9 313.9L565.4 351.3L583.4 358.5L578.2 379.1L589.9 394.6L573.6 424.2L585.2 436.8L634.5 418.5L650.9 436.2L633.0 451.4L615.3 478.2L631.3 494.2L610.8 519.5L594.0 527.6L569.2 531.2L561.6 546.2L540.0 562.2L522.6 560.4L512.3 535.8L466.4 534.4L442.1 550.7L427.6 552.7L408.9 542.1L382.3 554.2L357.7 508.4L329.9 519.0L318.3 516.5ZM433.0 419.1L431.6 375.3L429.9 391.5L433.0 419.1ZM463.4 443.1L497.2 460.9L485.5 452.4L463.4 443.1ZM458.3 482.8L488.6 467.8L497.2 460.9L458.3 482.8ZM541.2 470.5L531.3 466.6L497.2 460.9L541.2 470.5ZM552.3 425.8L546.1 437.1L531.3 466.6L552.3 425.8ZM545.4 384.1L545.7 392.5L552.3 425.8L545.4 384.1ZM516.9 369.1L489.3 349.1L525.0 375.7L545.4 384.1L516.9 369.1ZM372.1 446.5L368.6 452.8L362.3 478.4L372.1 446.5ZM440.5 438.2L441.4 445.3L445.4 431.5L440.5 438.2Z"""


# ── 데이터 훅 (세션 → Supabase 스냅샷 → 내장 샘플 폴백) ──────────
@st.cache_data(ttl=1800, show_spinner=False)
def _load_re_snapshot():
    """Supabase에 저장된 최신 부동산 스냅샷. 미설정/실패/테이블없음이면 None. (30분 캐시)"""
    try:
        from modules.db import supabase_configured, load_realestate
        if not supabase_configured():
            return None
        return load_realestate()
    except Exception:
        return None


@st.cache_data(ttl=1800, show_spinner=False)
def _load_recent_re_snapshots(days: int = 7):
    """최근 N일 부동산 스냅샷 행들(최신순). 주간 뷰용. 실패/미설정 → None. (30분 캐시)"""
    try:
        from modules.db import supabase_configured, load_recent_realestate
        if not supabase_configured():
            return None
        return load_recent_realestate(days)
    except Exception:
        return None


def _resolved_metrics():
    """지역 지표: 세션(직전 갱신) → DB 스냅샷 → None(샘플)."""
    m = st.session_state.get("re_metrics")
    if m:
        return m
    snap = _load_re_snapshot()
    return (snap or {}).get("metrics") if snap else None


def fetch_region_metrics():
    """지역명 -> {'mm','js','v','vc','jr'}. 세션→DB 스냅샷, 둘 다 없으면 None(샘플)."""
    return _resolved_metrics()


def _merged_regions():
    metrics = None
    try:
        metrics = fetch_region_metrics()
    except Exception:
        metrics = None
    if not metrics:
        return _GEO
    out = []
    for d in _GEO:
        m = metrics.get(d["n"]) or {}
        out.append({**d, **{k: m[k] for k in ("mm", "js", "v", "vc", "jr", "vavg") if k in m}})
    return out


# ── 권역 레벨(강남3구·서울·경기·수도권) — 지수 레벨 + 주간Δ + 추이 ──────────
#   엔진(collect_region_metrics)이 metrics 페이로드에 '_groups'/'_trend'로 실어 보낸다.
#   DB/세션에 없으면 아래 샘플로 폴백(화면이 비지 않게). 샘플은 상승장 가정.
def _sample_ramp(start, end, n=156):
    import math
    return [round(start + (end - start) * (i / (n - 1)) + 0.12 * math.sin(i / 6.0), 2)
            for i in range(n)]


_TREND_SAMPLE = {
    "gn3":   {"sale": _sample_ramp(101.0, 105.8), "jeonse": _sample_ramp(98.6, 101.2)},
    "seoul": {"sale": _sample_ramp(95.0, 98.2),   "jeonse": _sample_ramp(95.1, 97.4)},
    "gg":    {"sale": _sample_ramp(93.2, 94.6),   "jeonse": _sample_ramp(94.2, 95.8)},
    "all":   {"sale": _sample_ramp(93.9, 96.1),   "jeonse": _sample_ramp(94.4, 96.5)},
}
_GROUP_SAMPLE = {
    "gn3":   {"name": "강남3구", "sale": 105.8, "sale_wk": 0.24, "jeonse": 101.2,
              "jeonse_wk": 0.15, "jr": 51.3, "v": 412, "vc": 18},
    "seoul": {"name": "서울", "sale": 98.2, "sale_wk": 0.18, "jeonse": 97.4,
              "jeonse_wk": 0.09, "jr": 53.9, "v": 1840, "vc": 12},
    "gg":    {"name": "경기", "sale": 94.6, "sale_wk": 0.08, "jeonse": 95.8,
              "jeonse_wk": 0.11, "jr": 61.2, "v": 3210, "vc": 6},
    "all":   {"name": "수도권", "sale": 96.1, "sale_wk": 0.12, "jeonse": 96.5,
              "jeonse_wk": 0.10, "jr": 57.4, "v": 5050, "vc": 9},
}


def fetch_region_levels():
    """권역+시군구 레벨·추이 (groups, trend) 튜플.
    세션/DB metrics의 '_groups'/'_trend'(엔진 실데이터) → 샘플 폴백.
    엔진이 시군구(children)를 안 실어 보낸 경우 지도 샘플에서 시군구를 합성해 채운다."""
    m = _resolved_metrics()
    if isinstance(m, dict):
        g, t = m.get("_groups"), m.get("_trend")
        if g and t:
            return _augment_sigungu(g, t)
    return _augment_sigungu(_GROUP_SAMPLE, _TREND_SAMPLE)


_GU3 = ["강남구", "서초구", "송파구"]


def _augment_sigungu(groups, trend):
    """권역 groups/trend에 시군구(서울 구·경기 시) 레벨·추이를 보강.
    엔진이 이미 children을 실었으면(실데이터) 그대로 반환. 아니면 지도 샘플(_merged_regions의
    주간Δ·거래·전세가율)에서 결정적으로 합성해 아코디언이 폴백 상태에서도 동작하게 한다.
    레벨은 권역 샘플 대비 결정적 오프셋(지역 간 비교용 아님 — 데모/폴백 가독성용)."""
    if any("children" in (groups.get(k) or {}) for k in ("seoul", "gg")):
        return groups, trend
    g = copy.deepcopy(dict(groups))
    t = copy.deepcopy(dict(trend))
    try:
        regions = _merged_regions()
    except Exception:
        regions = []
    seoul_ch, gg_ch = [], []
    for d in regions:
        name, sd = d.get("n"), d.get("sd")
        if not name or sd not in ("seoul", "gg") or name in g:
            continue
        parent = "seoul" if sd == "seoul" else "gg"
        base = (g.get(parent) or {}).get("sale") or 100.0
        jbase = (g.get(parent) or {}).get("jeonse") or 96.0
        off = ((sum(ord(c) for c in name) % 21) - 10) * 0.45
        sale = round(base + off, 2)
        jeon = round(jbase + off * 0.7, 2)
        g[name] = {"name": name, "sale": sale, "sale_wk": d.get("mm", 0.0),
                   "jeonse": jeon, "jeonse_wk": d.get("js", 0.0),
                   "jr": d.get("jr"), "v": d.get("v", 0), "vc": d.get("vc", 0),
                   "leaf": True}
        t[name] = {"sale": _sample_ramp(sale - 3.0, sale),
                   "jeonse": _sample_ramp(jeon - 2.2, jeon)}
        (seoul_ch if parent == "seoul" else gg_ch).append(name)

    def _by_sale(n):
        s = g.get(n, {}).get("sale")
        return s if s is not None else -1.0
    seoul_ch.sort(key=_by_sale, reverse=True)
    gg_ch.sort(key=_by_sale, reverse=True)
    gn3_ch = sorted([n for n in _GU3 if n in g], key=_by_sale, reverse=True)
    if "gn3" in g:
        g["gn3"]["children"] = gn3_ch
    if "seoul" in g:
        g["seoul"]["children"] = seoul_ch
    if "gg" in g:
        g["gg"]["children"] = gg_ch
    if "all" in g:
        g["all"]["children"] = []
    return g, t


# ── 지표 (그룹 · 델타 · 기준선) ─────────────────────────────────
#   각 카드 dict: group/label/value/kind/col/series/note/dunit/baseline
#   거래량은 세션 re_metrics 합산, 금리는 한은 ECOS에서 실값을 끌어오고
#   실패하면 샘플 시리즈로 폴백한다(화면이 절대 비거나 깨지지 않게).
ECOS_MORTGAGE_STAT = "722Y001"   # 예금은행 가중평균금리(신규취급액 기준)
ECOS_MORTGAGE_ITEM = "BECABA03"  # 주택담보대출 ← 값이 안 맞으면 이 item 코드만 확인/교체
_RATE_SAMPLE = [4.35, 4.28, 4.20, 4.12, 4.05, 3.98, 3.92]


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_mortgage_rate():
    """한은 ECOS 주담대 가중평균금리(월, 최근 7개). 실패 시 None → 샘플 폴백. (1h 캐시)"""
    try:
        import requests
        from datetime import datetime
        key = ""
        try:
            key = st.secrets.get("ECOS_API_KEY", "")
        except Exception:
            key = ""
        if not key:
            return None
        end = datetime.now().strftime("%Y%m")
        start = f"{int(end[:4]) - 1}{end[4:]}"
        url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/24/"
               f"{ECOS_MORTGAGE_STAT}/M/{start}/{end}/{ECOS_MORTGAGE_ITEM}")
        r = requests.get(url, timeout=8)
        rows = r.json().get("StatisticSearch", {}).get("row", [])
        vals = [float(x["DATA_VALUE"]) for x in rows if x.get("DATA_VALUE")]
        return vals[-7:] if len(vals) >= 2 else None
    except Exception:
        return None


def _kb_value_series(df, decimals=1, points=7):
    """KB Kbland 결과 df → 값 시리즈(날짜 정렬·값 컬럼 자동탐색).
       points=N이면 최근 N개, None이면 전체. 실패 시 None."""
    import pandas as pd
    if df is None or len(df) == 0:
        return None
    if "날짜" in df.columns:
        df = df.sort_values("날짜")
    valcol = None
    for c in reversed(list(df.columns)):
        if c == "지역코드":
            continue
        s = pd.to_numeric(df[c], errors="coerce")
        if s.notna().sum() >= 2:
            valcol = c
            df = df.assign(**{c: s})
            break
    if valcol is None:
        return None
    vals = [float(v) for v in df[valcol].tolist() if v == v]
    if len(vals) < 2:
        return None
    if points is not None:
        vals = vals[-points:]
    return [round(v, decimals) for v in vals]


@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_kb_buy_superiority():
    """KB 주간 매수우위지수(서울). 키 불필요. 실패 시 None → 샘플. (6h 캐시)"""
    try:
        from PublicDataReader import Kbland
        df = Kbland().get_market_trend(
            메뉴코드="01", 월간주간구분코드="02", 지역코드="11", 기간="1")
        return _kb_value_series(df, 1)
    except Exception:
        return None


@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_kb_sales_index():
    """KB 주간 아파트 매매가격지수(서울). 키 불필요. 실패 시 None → 샘플."""
    try:
        from PublicDataReader import Kbland
        df = Kbland().get_price_index(
            월간주간구분코드="02", 매물종별구분="01", 매매전세코드="01",
            지역코드="11", 기간="1")
        return _kb_value_series(df, 2)
    except Exception:
        return None


@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_kb_jeonse_ratio():
    """KB 아파트 전세가격비율(서울, 월간). 키 불필요. 실패 시 None → 샘플."""
    try:
        from PublicDataReader import Kbland
        df = Kbland().get_jeonse_price_ratio("01", 지역코드="11", 기간="1")
        return _kb_value_series(df, 1)
    except Exception:
        return None


@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_kb_jeonse_index():
    """KB 주간 아파트 전세가격지수(서울). 키 불필요. 실패 시 None → 샘플."""
    try:
        from PublicDataReader import Kbland
        df = Kbland().get_price_index(
            월간주간구분코드="02", 매물종별구분="01", 매매전세코드="02",
            지역코드="11", 기간="1")
        return _kb_value_series(df, 2)
    except Exception:
        return None


# ── 차트 추이용 전체 시리즈 (주간 · 최근값 다수) ──────────────────
#   KB가 주는 만큼만 실데이터로 사용 · 부족하면 컴포넌트에서 합성 폴백.
@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_kb_sales_index_full():
    try:
        from PublicDataReader import Kbland
        df = Kbland().get_price_index(
            월간주간구분코드="02", 매물종별구분="01", 매매전세코드="01",
            지역코드="11", 기간="1")
        return _kb_value_series(df, 2, points=None)
    except Exception:
        return None


@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_kb_jeonse_index_full():
    try:
        from PublicDataReader import Kbland
        df = Kbland().get_price_index(
            월간주간구분코드="02", 매물종별구분="01", 매매전세코드="02",
            지역코드="11", 기간="1")
        return _kb_value_series(df, 2, points=None)
    except Exception:
        return None


@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_kb_buy_superiority_full():
    try:
        from PublicDataReader import Kbland
        df = Kbland().get_market_trend(
            메뉴코드="01", 월간주간구분코드="02", 지역코드="11", 기간="1")
        return _kb_value_series(df, 1, points=None)
    except Exception:
        return None


# KOSIS 미분양주택현황(시도/시군구) DT_1YL202001E · 항목=미분양현황 · objL1=전국
_KOSIS_UNSOLD = {"org": "101", "tbl": "DT_1YL202001E",
                 "itm": "13103871087T1", "obj": "13102871087A.0002"}


@st.cache_data(ttl=21600, show_spinner=False)
def _fetch_kosis_unsold():
    """KOSIS 전국 미분양(월, 최근 7개) → 만호 단위. KOSIS_API_KEY 필요. 실패 시 None → 샘플."""
    try:
        import pandas as pd
        key = ""
        try:
            key = st.secrets.get("KOSIS_API_KEY", "")
        except Exception:
            key = ""
        if not key:
            return None
        from PublicDataReader import Kosis
        df = Kosis(key).get_data(
            "통계자료", orgId=_KOSIS_UNSOLD["org"], tblId=_KOSIS_UNSOLD["tbl"],
            itmId=_KOSIS_UNSOLD["itm"], objL1=_KOSIS_UNSOLD["obj"],
            prdSe="M", newEstPrdCnt="14")
        if df is None or len(df) == 0:
            return None
        pcol = next((c for c in df.columns if "시점" in c or c.upper() == "PRD_DE"), None)
        vcol = next((c for c in df.columns if "수치" in c or c.upper() == "DT"), None)
        if vcol is None:
            for c in reversed(list(df.columns)):
                if pd.to_numeric(df[c], errors="coerce").notna().sum() >= 2:
                    vcol = c
                    break
        if vcol is None:
            return None
        if pcol:
            df = df.sort_values(pcol)
        vals = [v for v in pd.to_numeric(df[vcol], errors="coerce").tolist() if v == v]
        out = [round(v / 10000, 1) for v in vals[-7:]]
        return out if len(out) >= 2 else None
    except Exception:
        return None


def _live_volume():
    """수도권 주간 실거래 (총건수, 전주비 평균%). 세션→DB 스냅샷, 없으면 None."""
    m = _resolved_metrics()
    if not m:
        return None
    try:
        total = int(sum(r.get("v", 0) for r in m.values()))
        vcs = [r["vc"] for r in m.values() if "vc" in r]
        avg_vc = round(sum(vcs) / len(vcs), 1) if vcs else 0.0
        return total, avg_vc
    except Exception:
        return None


def fetch_indicators():
    """그룹별 지표 카드 리스트. 거래량·금리는 실값 우선, 나머지는 샘플(연결 예정)."""
    vol = _live_volume()
    if vol:
        v_total, v_vc = vol
        vol_card = {"group": "선행·심리", "label": "주간 실거래량(수도권)",
                    "value": f"{v_total:,}건", "kind": "bar", "col": "#7E9A83",
                    "series": [int(v_total * x) for x in (.82, .78, .9, .85, .94, .97, 1.0)],
                    "note": "국토부 실거래 합산 · 전주비 "
                            + (f"+{v_vc}%" if v_vc >= 0 else f"{v_vc}%"),
                    "dunit": "건", "baseline": None}
    else:
        vol_card = {"group": "선행·심리", "label": "주간 실거래량(수도권)",
                    "value": "2,594건", "kind": "bar", "col": "#7E9A83",
                    "series": [2120, 2030, 2350, 2210, 2440, 2510, 2594],
                    "note": "국토부 실거래 · '갱신' 누르면 실값(현재 샘플)",
                    "dunit": "건", "baseline": None}

    rate_live = _fetch_mortgage_rate()
    rate = rate_live or _RATE_SAMPLE
    rate_card = {"group": "금융", "label": "주담대 금리(가중평균)",
                 "value": f"{rate[-1]:.2f}%", "kind": "line", "col": "#5A7CA0",
                 "series": rate, "dunit": "%p", "baseline": None,
                 "note": "한은 ECOS · 신규취급 가중평균" if rate_live
                         else "한은 ECOS · 키/코드 확인 전 샘플"}

    kb_live = _fetch_kb_buy_superiority()
    kb_series = kb_live or [44, 46, 49, 52, 55, 57, 58.4]
    kb_card = {"group": "선행·심리", "label": "매수우위지수",
               "value": f"{kb_series[-1]:.1f}", "kind": "line", "col": "#7E9A83",
               "series": kb_series, "dunit": "p", "baseline": 100,
               "note": "KB 주간 · 100=중립" if kb_live
                       else "KB 주간 · 100=중립(현재 샘플)"}

    unsold_live = _fetch_kosis_unsold()
    unsold = unsold_live or [7.2, 7, 6.8, 6.6, 6.4, 6.2, 6.1]
    unsold_card = {"group": "공급·펀더멘털", "label": "미분양(전국)",
                   "value": f"{unsold[-1]:.1f}만", "kind": "bar", "col": "#B65F5A",
                   "series": unsold, "dunit": "만", "baseline": None,
                   "note": "KOSIS 미분양현황 · 월간 · 적을수록 수급 양호" if unsold_live
                           else "KOSIS 미분양현황 · 키/표 확인 전 샘플"}

    mi_live = _fetch_kb_sales_index()
    mi = mi_live or [95.6, 95.7, 95.9, 96.0, 96.1, 96.2, 96.3]
    if mi_live and len(mi) >= 2 and mi[-2]:
        _wk = (mi[-1] / mi[-2] - 1) * 100
        mi_note = f"KB 주간 아파트 매매가격지수(서울) · 주간 {_wk:+.2f}%"
    else:
        mi_note = "KB 주간 매매가격지수(서울) · 확인 전 샘플"
    mi_card = {"group": "가격(동행)", "label": "매매 주간지수(서울)",
               "value": f"{mi[-1]:.1f}", "kind": "line", "col": "#B65F5A",
               "series": mi, "dunit": "p", "baseline": None, "note": mi_note}

    jr_live = _fetch_kb_jeonse_ratio()
    jr = jr_live or [57, 56.5, 56, 55.5, 55.1, 54.9, 54.8]
    jr_card = {"group": "가격(동행)", "label": "전세가율(서울 아파트)",
               "value": f"{jr[-1]:.1f}%", "kind": "line", "col": "#5A7CA0",
               "series": jr, "dunit": "%p", "baseline": None,
               "note": "KB 월간 · 갭·전세 레버리지" if jr_live
                       else "KB 전세가격비율 · 확인 전 샘플"}

    return [
        kb_card,
        vol_card,
        mi_card,
        jr_card,
        unsold_card,
        {"group": "공급·펀더멘털", "label": "인구·세대수(수도권)", "value": "13,420천", "kind": "bar",
         "col": "#A7BBA9", "series": [13380, 13390, 13400, 13405, 13410, 13418, 13420],
         "note": "KOSIS 주민등록인구 · 표 확정 후 연결(현재 샘플)", "dunit": "천", "baseline": None},
        rate_card,
    ]


# ── 지표 시계열 (엔진 collect_indicators가 DB에 저장하는 새 형식) ──────────
#   각 항목: {key,label,sub,unit,col,series[...]} · 가격지수는 전부 KB(신뢰 소스).
#   메타(차트 표시용): short=카드 라벨 · cadence=주/월 · baseline=중립선 · dp=델타 단위
_IND_META = {
    "sale":    ("매매지수", "week", 100, "%"),
    "jeonse":  ("전세지수", "week", 100, "%"),
    "lead50":  ("선도50지수", "week", 100, "%"),
    "buy":     ("매수우위", "week", 100, "p"),
    "jsup":    ("전세수급", "week", 100, "p"),
    "outlook": ("매매전망", "month", 100, "p"),
    "jr":      ("전세가율", "month", 100, "p"),
}
# baseline(중립선 100)이 의미 있는 심리지표만 — 매수우위·전세수급·매매전망
_IND_BASELINE = {"buy": 100, "jsup": 100, "outlook": 100}

# ── 지표 탭 v2: 의미 레이어(사이클·그룹·신호·해석) 메타 ───────────────
#   g=그룹 · baseline=중립선(없으면 None) · inv=역행(낮을수록 시장 긍정) · interp=한 줄 해석
_INDV2_GROUPS = {
    "lead":   {"name": "선행지표", "desc": "먼저 움직인다 — 방향 신호"},
    "coin":   {"name": "동행지표", "desc": "지금 가격·거래"},
    "supply": {"name": "수급·심리", "desc": "전세·갭·기대"},
}
_INDV2_DEF = {
    "buy":      {"g": "lead", "cad": "week", "baseline": 100, "inv": False,
                 "interp": "100 넘으면 매수자 우위·과열권. 매수 심리의 선행 신호."},
    "outlook":  {"g": "lead", "cad": "month", "baseline": 100, "inv": False,
                 "interp": "100 위 = 상승 기대 우세. 향후 가격 방향의 선행."},
    "lead50":   {"g": "lead", "cad": "week", "baseline": None, "inv": False,
                 "interp": "상급지 50단지가 시장을 선도—먼저 반등/하락(매매지수와 강상관)."},
    "sale":     {"g": "coin", "cad": "week", "baseline": None, "inv": False,
                 "interp": "실제 매매가 레벨. 시장의 '현재값'."},
    "jeonse":   {"g": "coin", "cad": "week", "baseline": None, "inv": False,
                 "interp": "전세가 레벨. 오르면 매매 하방을 받쳐줌."},
    "jsup":     {"g": "supply", "cad": "week", "baseline": 100, "inv": False,
                 "interp": "100 위 = 전세 공급부족(수요>공급). 전세·매매 동반 자극."},
    "jr":       {"g": "supply", "cad": "month", "baseline": None, "inv": False,
                 "interp": "전세/매매 비율. 높을수록 갭 부담↓·하방 지지↑."},
    "joutlook": {"g": "supply", "cad": "month", "baseline": 100, "inv": False,
                 "interp": "전세 상승 기대. 전세 불안의 선행 신호."},
}
# 카드 표시 순서(그룹 보기 내 정렬). 선도50은 선행 보조로 매매전망 뒤에 둠.
_INDV2_ORDER = ["buy", "outlook", "lead50", "sale", "jeonse",
                "jsup", "jr", "joutlook"]
# 핵심(상단 강조 카드).
_INDV2_CORE = ("buy", "outlook")
# 연결예정 슬롯 — 데이터 소스 자체가 아직 미연결(진짜 '연결예정'). 가짜 데이터 없음.
# (경매 낙찰가율·입주물량 제거 — 2026-07)
_INDV2_PENDING = []

# 엔진 연결 전(또는 DB 비었을 때) 샘플 — 현재 상승장 반영(가짜로 하락처럼 안 보이게)
_IND_SAMPLE = [
    {"key": "sale", "label": "매매가격지수", "sub": "서울 · 주간(KB)", "unit": "", "col": "#B65F5A",
     "series": [94.1, 94.3, 94.6, 94.9, 95.1, 95.4, 95.6, 95.9, 96.1, 96.4,
                96.6, 96.9, 97.1, 97.3, 97.5, 97.7, 97.9, 98.0, 98.1, 98.2]},
    {"key": "jeonse", "label": "전세가격지수", "sub": "서울 · 주간(KB)", "unit": "", "col": "#5A7CA0",
     "series": [95.0, 95.2, 95.4, 95.6, 95.8, 96.0, 96.1, 96.3, 96.4, 96.6,
                96.7, 96.8, 96.9, 97.0, 97.1, 97.2, 97.3, 97.3, 97.4, 97.4]},
    {"key": "lead50", "label": "선도아파트50지수", "sub": "전국 · 주간(KB) · 상위 50개 단지", "unit": "", "col": "#A35F5A",
     "series": [94.8, 95.2, 95.7, 96.2, 96.6, 97.1, 97.6, 98.0, 98.5, 98.9,
                99.3, 99.8, 100.2, 100.5, 100.9, 101.2, 101.5, 101.8, 102.0, 102.2]},
    {"key": "buy", "label": "매수우위지수", "sub": "서울 · 주간(KB) · 100=중립", "unit": "", "col": "#B89A5C",
     "series": [34, 37, 41, 44, 47, 50, 53, 56, 58, 61, 63, 66, 68, 70, 72, 73, 75, 76, 77, 77]},
    {"key": "jsup", "label": "전세수급지수", "sub": "서울 · 주간(KB) · 100=균형", "unit": "", "col": "#6E8FA8",
     "series": [108, 111, 114, 117, 120, 123, 126, 128, 131, 133, 135, 137, 139, 140, 142, 143, 144, 145, 145, 146]},
    {"key": "outlook", "label": "매매가격전망지수", "sub": "서울 · 월간(KB) · 100=중립", "unit": "", "col": "#C2A05A",
     "series": [96, 98, 101, 104, 107, 109, 112, 114, 116, 117, 118, 119]},
    {"key": "joutlook", "label": "전세가격전망지수", "sub": "서울 · 월간(KB) · 100=중립", "unit": "", "col": "#8AA0B5",
     "series": [97, 99, 101, 103, 105, 107, 108, 110, 111, 111, 112, 112]},
    {"key": "jr", "label": "전세가율", "sub": "서울 · 월간(KB)", "unit": "%", "col": "#7E9A83",
     "series": [51.4, 51.7, 52.0, 52.3, 52.6, 52.9, 53.1, 53.3, 53.5, 53.7, 53.8, 53.9]},
    # 서울·수도권 매매 중위/평균가격(억) — 지표탭 '현재 매매가격' 블록용(카드 아님)
    {"key": "med_seoul", "label": "서울 아파트 매매 중위가격", "sub": "서울 · 월간(KB)", "unit": "억", "col": "#7E9A83",
     "series": [9.8, 9.9, 10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9]},
    {"key": "mean_seoul", "label": "서울 아파트 매매 평균가격", "sub": "서울 · 월간(KB)", "unit": "억", "col": "#7E9A83",
     "series": [12.6, 12.7, 12.8, 12.9, 13.0, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7]},
    {"key": "med_sudo", "label": "수도권 아파트 매매 중위가격", "sub": "수도권 · 월간(KB)", "unit": "억", "col": "#7E9A83",
     "series": [6.20, 6.25, 6.30, 6.35, 6.40, 6.45, 6.50, 6.55, 6.60, 6.65, 6.70, 6.75]},
    {"key": "mean_sudo", "label": "수도권 아파트 매매 평균가격", "sub": "수도권 · 월간(KB)", "unit": "억", "col": "#7E9A83",
     "series": [7.00, 7.05, 7.10, 7.15, 7.20, 7.25, 7.30, 7.35, 7.40, 7.45, 7.50, 7.55]},
]


def _resolved_indicator_series():
    """지표 시계열: 세션 → DB 스냅샷(새 형식 list[{...,'series'}]) → 샘플.
    옛 형식/None이면 샘플로 폴백(화면이 비거나 가짜 하락으로 보이지 않게)."""
    s = st.session_state.get("re_indseries")
    if s:
        return s
    snap = _load_re_snapshot()
    inds = (snap or {}).get("indicators") if snap else None
    if (isinstance(inds, list) and inds and isinstance(inds[0], dict)
            and "series" in inds[0]):
        return inds
    return _IND_SAMPLE


def _phase_from_series(data):
    """지표 시계열로 규칙기반 '시장 국면' 한 줄(비용 0)."""
    by = {it.get("key"): [v for v in (it.get("series") or []) if v is not None]
          for it in data}

    def tr(k):
        s = by.get(k) or []
        return (s[-1] - s[-2]) if len(s) >= 2 else 0

    seg = ["가격 " + ("상승" if tr("sale") > 0 else "하락" if tr("sale") < 0 else "보합")]
    if by.get("buy"):
        seg.append("심리 " + ("매수우위" if by["buy"][-1] >= 100 else "매도우위"))
    spans = '<span style="color:#C9CBC2;margin:0 2px">·</span>'.join(
        f'<span class="seg">{s}</span>' for s in seg)
    return f'<div class="re-phase"><b>시장 국면</b>{spans}</div>'


# (유형,배경,글자색,단지,지역,면적,가격,변동,거래유형,제외,거래일ISO,세대수,빈도,신호강도%)
_SAMPLE_ANOMALIES = [
    ("신고가", "#FCEBEB", "#A32D2D", "래미안원베일리", "서초구", "84㎡", "58.0억", "+3.2%", "중개", False, "2026-06-20", 2990, 18, 3.2),
    ("신고가", "#FCEBEB", "#A32D2D", "힐스테이트판교엘포레", "성남시", "84㎡", "24.5억", "+2.6%", "중개", False, "2026-06-19", 1185, 14, 2.6),
    ("거래량 급증", "#FAEEDA", "#854F0B", "파크리오", "송파구", "전체", "12건/4주", "+148%", "-", False, "2026-06-20", 6864, 40, 148.0),
    ("급등", "#FCEBEB", "#A32D2D", "광교중흥S클래스", "수원시", "84㎡", "17.8억", "+8.1%", "중개", False, "2026-06-18", 2231, 16, 8.1),
    ("신저가", "#E6F1FB", "#0C447C", "상계주공7", "노원구", "59㎡", "6.1억", "-4.0%", "중개", False, "2026-06-19", 2634, 22, 4.0),
    ("급락", "#E6F1FB", "#0C447C", "은마", "강남구", "84㎡", "26.0억", "-7.5%", "직거래", True, "2026-06-17", 4424, 20, 7.5),
]


def fetch_anomalies():
    """특이거래 리스트. 세션 → DB 스냅샷 → 샘플."""
    a = st.session_state.get("re_anoms")
    if a:
        return a
    snap = _load_re_snapshot()
    if snap and snap.get("anomalies"):
        return snap["anomalies"]
    return _SAMPLE_ANOMALIES


# ── 주목 단지(최근 거래 활발·상승 · 국토부 실거래) ────────────────────────
_SAMPLE_HOT = [
    {"apt": "파크리오", "gu": "송파구", "sd": "seoul", "addr": "송파구 잠실동",
     "units": 6864, "builder": "대우건설", "recent": 14, "prev": 6, "vol_chg": 133, "vol_mult": 4.7,
     "chg": 2.1, "freq": 40, "p59_eok": "18.4억", "p84_eok": "24.8억",
     "jr": 54, "gap_eok": 11.4, "spark": [2620,2635,2628,2650,2662,2671,2688]},
    {"apt": "헬리오시티", "gu": "송파구", "sd": "seoul", "addr": "송파구 가락동",
     "units": 9510, "builder": "현대건설", "recent": 12, "prev": 7, "vol_chg": 71, "vol_mult": 3.4,
     "chg": 1.6, "freq": 51, "p59_eok": "17.6억", "p84_eok": "23.5억",
     "jr": 57, "gap_eok": 10.1, "spark": [2470,2485,2478,2492,2505,2511,2503]},
    {"apt": "잠실엘스", "gu": "송파구", "sd": "seoul", "addr": "송파구 잠실동",
     "units": 5678, "builder": "삼성물산", "recent": 9, "prev": 5, "vol_chg": 80, "vol_mult": 3.6,
     "chg": 2.4, "freq": 33, "p59_eok": "19.5억", "p84_eok": "27.0억",
     "jr": 58, "gap_eok": 11.3, "spark": [2833,2857,2845,2869,2893,2917,2940]},
    {"apt": "래미안원베일리", "gu": "서초구", "sd": "seoul", "addr": "서초구 반포동",
     "units": 2990, "builder": "삼성물산", "recent": 7, "prev": 3, "vol_chg": 133, "vol_mult": 4.7,
     "chg": 3.2, "freq": 18, "p59_eok": None, "p84_eok": "58.0억",
     "jr": 49, "gap_eok": 29.6, "spark": [6900,6980,6940,7010,7120]},
    {"apt": "고덕그라시움", "gu": "강동구", "sd": "seoul", "addr": "강동구 고덕동",
     "units": 4932, "builder": "대우건설", "recent": 8, "prev": 6, "vol_chg": 33, "vol_mult": 2.7,
     "chg": 0.9, "freq": 29, "p59_eok": "13.4억", "p84_eok": "17.2억",
     "jr": 62, "gap_eok": 6.5, "spark": [2040,2055,2048,2061,2058]},
    {"apt": "광교중흥S클래스", "gu": "수원시", "sd": "gg", "addr": "수원시 하동",
     "units": 2231, "builder": "중흥토건", "recent": 6, "prev": 4, "vol_chg": 50, "vol_mult": 3.0,
     "chg": 1.4, "freq": 16, "p59_eok": "13.2억", "p84_eok": "17.8억",
     "jr": 66, "gap_eok": 6.1, "spark": [1760,1772,1768,1781,1795]},
]


def fetch_hot_complexes():
    """주목 단지 리스트. 세션/DB metrics의 '_hot' → 샘플 폴백."""
    m = _resolved_metrics()
    if isinstance(m, dict) and m.get("_hot"):
        return m["_hot"]
    return _SAMPLE_HOT


# ── 구별 시가총액 상위 단지 (시총=최근 실거래가×세대수 · 국토부+공동주택) ──────
#   엔진(collect_hot_complexes with_cap)이 metrics['_caplead']에 실어 보냄(스키마 무변경).
#   엔트리: {apt,gu,sd,units,builder,price_eok,cap_eok,cap_fmt,p59_eok,p84_eok,dong,addr,...}
#   (apt,gu,units,cap_eok,price_eok,builder,dong)
_CAPLEAD_ROWS = [
    ("래미안원베일리", "서초구", 2990, 173420, "58.0억", "삼성물산", "반포동"),
    ("헬리오시티", "송파구", 9510, 161670, "17.0억", "현대건설", "가락동"),
    ("반포자이", "서초구", 3410, 143220, "42.0억", "GS건설", "반포동"),
    ("파크리오", "송파구", 6864, 123552, "18.0억", "대우건설", "잠실동"),
    ("은마", "강남구", 4424, 115024, "26.0억", None, "대치동"),
    ("잠실엘스", "송파구", 5678, 110721, "19.5억", "삼성물산", "잠실동"),
    ("래미안퍼스티지", "서초구", 2444, 109980, "45.0억", "삼성물산", "반포동"),
    ("리센츠", "송파구", 5563, 105697, "19.0억", None, "잠실동"),
    ("개포자이프레지던스", "강남구", 3375, 104625, "31.0억", "GS건설", "개포동"),
    ("아크로리버파크", "서초구", 1612, 88660, "55.0억", "대림산업", "반포동"),
    ("고덕그라시움", "강동구", 4932, 84830, "17.2억", "대우건설", "고덕동"),
    ("마포래미안푸르지오", "마포구", 3885, 73815, "19.0억", "삼성물산", "아현동"),
    ("트리지움", "송파구", 3696, 68376, "18.5억", None, "잠실동"),
    ("고덕아르테온", "강동구", 4057, 68158, "16.8억", "현대건설", "상일동"),
    ("래미안블레스티지", "강남구", 1957, 58710, "30.0억", "삼성물산", "개포동"),
    ("고덕래미안힐스테이트", "강동구", 3658, 58528, "16.0억", "삼성물산", "고덕동"),
    ("래미안첼리투스", "용산구", 1140, 51300, "45.0억", "삼성물산", "이촌동"),
    ("래미안대치팰리스", "강남구", 1278, 48564, "38.0억", "삼성물산", "대치동"),
    ("디에이치아너힐즈", "강남구", 1320, 44880, "34.0억", "현대건설", "개포동"),
    ("e편한세상옥수파크힐스", "성동구", 1976, 41496, "21.0억", "대림산업", "옥수동"),
    ("광교중흥에스클래스", "수원시", 2231, 39712, "17.8억", "중흥토건", "하동"),
    ("용산센트럴파크", "용산구", 1140, 37620, "33.0억", None, "한강로"),
    ("마포프레스티지자이", "마포구", 1694, 35574, "21.0억", "GS건설", "염리동"),
    ("래미안옥수리버젠", "성동구", 1511, 33242, "22.0억", "삼성물산", "옥수동"),
    ("반포래미안아이파크", "서초구", 829, 33160, "40.0억", "삼성물산", "잠원동"),
    ("래미안솔베뉴", "강동구", 1900, 27550, "14.5억", "삼성물산", "명일동"),
    ("고덕센트럴아이파크", "강동구", 1745, 27048, "15.5억", "현대산업", "상일동"),
    ("광교자연앤힐스테이트", "수원시", 1764, 26460, "15.0억", "현대건설", "이의동"),
    ("영통아이파크캐슬", "수원시", 2666, 25327, "9.5억", "현대산업", "망포동"),
    ("신촌그랑자이", "마포구", 1248, 24960, "20.0억", "GS건설", "대흥동"),
    ("상계주공7", "노원구", 2634, 18438, "7.0억", None, "상계동"),
    ("광교호반베르디움", "수원시", 1330, 17290, "13.0억", "호반건설", "이의동"),
    ("광교더샵", "수원시", 686, 10976, "16.0억", "포스코", "원천동"),
    ("미아뉴타운두산위브", "강북구", 1370, 10960, "8.0억", "두산", "미아동"),
    ("창동주공19", "도봉구", 1764, 10584, "6.0억", None, "창동"),
    ("불암현대", "노원구", 825, 5363, "6.5억", None, "중계동"),
]
_SAMPLE_CAPLEAD = [
    {"apt": a, "gu": g, "units": u, "cap_eok": c, "price_eok": p,
     "builder": b, "dong": d}
    for (a, g, u, c, p, b, d) in _CAPLEAD_ROWS
]


def fetch_cap_leaders():
    """구별 시가총액 상위 단지. 세션/DB metrics의 '_caplead' → 샘플 폴백."""
    m = _resolved_metrics()
    if isinstance(m, dict) and m.get("_caplead"):
        return m["_caplead"]
    return _SAMPLE_CAPLEAD


# ── 작년말 대비 시총(=매매가) 상승률 상위 단지 (전년 12월 vs 현재 평단가) ──────
#   엔진(collect_hot_complexes with_gain)이 metrics['_capgain']에 실어 보냄.
#   (apt, gu, units, yoy%, price_eok, cap_fmt, dong)
_CAPGAIN_ROWS = [
    ("잠실엘스", "송파구", 5678, 18.5, "19.5억", "11.1조", "잠실동"),
    ("헬리오시티", "송파구", 9510, 16.2, "17.0억", "16.2조", "가락동"),
    ("래미안원베일리", "서초구", 2990, 14.8, "58.0억", "17.3조", "반포동"),
    ("e편한세상옥수파크힐스", "성동구", 1976, 13.9, "21.0억", "4.1조", "옥수동"),
    ("광장현대파크빌", "광진구", 1170, 12.6, "20.5억", "2.4조", "광장동"),
    ("마포래미안푸르지오", "마포구", 3885, 11.4, "19.0억", "7.4조", "아현동"),
    ("고덕그라시움", "강동구", 4932, 10.2, "17.2억", "8.5조", "고덕동"),
    ("래미안대치팰리스", "강남구", 1278, 9.5, "38.0억", "4.9조", "대치동"),
    ("광교중흥에스클래스", "수원시", 2231, 8.1, "17.8억", "4.0조", "하동"),
    ("파크리오", "송파구", 6864, 7.3, "18.0억", "12.4조", "잠실동"),
]
_SAMPLE_CAPGAIN = [
    {"apt": a, "gu": g, "units": u, "yoy": y, "mom": round(y * 0.28, 1),
     "price_eok": p, "cap_fmt": cf, "dong": d}
    for (a, g, u, y, p, cf, d) in _CAPGAIN_ROWS
]


def fetch_cap_gainers():
    """작년말 대비 시총 상승률 상위 단지. 세션/DB metrics의 '_capgain' → 샘플 폴백."""
    m = _resolved_metrics()
    if isinstance(m, dict) and m.get("_capgain"):
        return m["_capgain"]
    return _SAMPLE_CAPGAIN


# ── 분양 단지 (청약홈 분양정보 — 현재 샘플 · 폴백) ───────────────
#   (단지명, 시군구, 주소, 유형, 공급세대, 청약시작 'MM.DD', 청약종료, 입주예정 'YY.MM', seoul|gg)
#   실연결: 한국부동산원 청약홈 분양정보 조회 서비스(data.go.kr/15098547) — 별도 활용신청 필요.
_SAMPLE_SUBS = [
    ("래미안 OO포레", "서초구", "서울 서초구 방배동", "민영", 689, "06.16", "06.18", "28.09", "seoul"),
    ("OO자이 디에이치", "강동구", "서울 강동구 천호동", "민영", 1248, "06.23", "06.25", "28.12", "seoul"),
    ("광명 OO푸르지오", "광명시", "경기 광명시 광명동", "민영", 1051, "06.17", "06.19", "28.06", "gg"),
    ("수원 OO트리니티", "수원시", "경기 수원시 영통구", "민영", 842, "06.30", "07.02", "28.10", "gg"),
    ("용인 OO센트럴", "용인시", "경기 용인시 처인구", "민영", 1395, "07.07", "07.09", "29.02", "gg"),
    ("은평 OO엘리프", "은평구", "서울 은평구 대조동", "민영", 423, "05.26", "05.28", "27.11", "seoul"),
    ("화성동탄 OO리슈빌", "화성시", "경기 화성시 동탄2", "민영", 614, "05.19", "05.21", "27.08", "gg"),
]

# 청약홈 APT 분양정보 목록 — 개별 공고 url이 없을 때(샘플·구 스냅샷) 폴백 이동지.
_APPLYHOME_LIST = "https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancListView.do"


def fetch_subscriptions():
    """분양 단지 리스트. 세션(직전 갱신)→DB 스냅샷→내장 샘플 폴백.
       DB/세션 값이면 실데이터, _SAMPLE_SUBS 객체면 샘플(렌더에서 identity로 구분)."""
    s = st.session_state.get("re_subs")
    if s:
        return s
    snap = _load_re_snapshot()
    if snap:
        subs = snap.get("subscriptions")
        if subs:
            return subs
    return _SAMPLE_SUBS


def _sub_window(start, end):
    """'MM.DD' 청약 기간 → (시작date, 종료date). 연말연초 이월 보정. 실패 시 (None, None)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    try:
        y = today.year
        s = datetime.strptime(f"{y}.{start}", "%Y.%m.%d").date()
        e = datetime.strptime(f"{y}.{end}", "%Y.%m.%d").date()
    except Exception:
        return None, None
    try:
        if e < today - timedelta(days=300):       # 사실상 내년 건(연초)
            s = s.replace(year=s.year + 1)
            e = e.replace(year=e.year + 1)
        elif s > today + timedelta(days=300):     # 사실상 작년 건(연말)
            s = s.replace(year=s.year - 1)
            e = e.replace(year=e.year - 1)
    except ValueError:
        pass
    return s, e


def _sub_status(start, end):
    """청약 기간으로 예정/분양중/마감 분류 (KST 기준). (라벨, 정렬순)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    s, e = _sub_window(start, end)
    if s is None:
        return "예정", 1
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    if today < s:
        return "예정", 1
    if s <= today <= e:
        return "분양중", 0
    return "마감", 2


def _sub_dday(s_date, e_date, status):
    """상태별 D-day 배지 텍스트. 예정=시작까지, 분양중=마감까지."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    if s_date is None:
        return status
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    if status == "예정":
        n = (s_date - today).days
        return "D-DAY" if n <= 0 else f"D-{n}"
    if status == "분양중":
        n = (e_date - today).days
        return "오늘 마감" if n <= 0 else f"마감 D-{n}"
    return "마감"


# ── 지표·거래 카드 CSS (부모 문서 · 전역 변수 사용) ──────────────
_RE_CSS = """
<style>
.re-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:12px;margin-top:6px;}
.re-card{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:14px;padding:13px 15px;
  transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease;}
.re-card:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(52,53,47,.08);border-color:var(--sage,#A7BBA9);}
.re-lab{font-size:12px;font-weight:600;color:var(--muted,#9a9b92);}
.re-val{font-size:22px;font-weight:700;color:var(--ink,#34352f);margin:2px 0 6px;letter-spacing:-.02em;}
.re-spark{width:100%;height:46px;display:block;}
.re-note{font-size:11px;color:var(--muted,#9a9b92);margin-top:6px;}
.re-anom{display:flex;align-items:center;gap:12px;background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);
  border-radius:12px;padding:10px 13px;margin-bottom:8px;
  transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease;}
.re-anom:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(52,53,47,.07);border-color:var(--sage,#A7BBA9);}
.re-anom.excl{opacity:.5;}
.re-bdg{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:6px;flex:none;}
.re-apt{font-weight:700;color:var(--ink,#34352f);}
.re-sub{font-size:12px;color:var(--muted,#9a9b92);}
.re-price{font-weight:700;color:var(--ink,#34352f);text-align:right;}
.re-chg{font-size:12px;font-weight:700;text-align:right;}
.re-chg.up{color:var(--up,#B65F5A);} .re-chg.dn{color:var(--down,#5A7CA0);}
.re-chg.lv1{font-size:13px;}
.re-chg.lv2{font-size:15px;letter-spacing:-.01em;}
.re-apt a{color:inherit;text-decoration:none;border-bottom:1px dashed #D6D8CF;}
.re-apt a:hover{border-bottom-color:var(--sage,#A7BBA9);}
.re-statband{display:flex;flex-wrap:wrap;gap:8px;margin:2px 0 12px;}
.re-stat{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:10px;
  padding:7px 12px;font-size:12.5px;color:var(--ink,#34352f);}
.re-stat b{font-size:16px;font-weight:800;margin-right:4px;letter-spacing:-.02em;}
.re-daygroup{font-size:11.5px;font-weight:700;color:var(--muted,#9a9b92);margin:12px 2px 6px;
  display:flex;align-items:center;gap:8px;}
.re-daygroup::after{content:"";flex:1;height:1px;background:var(--line,#ECEDE7);}
/* 상승압력 게이지 */
.re-press{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 12px;font-size:11.5px;color:var(--muted,#9a9b92);}
.re-press .lab b{color:var(--ink,#34352f);font-weight:800;}
.re-press .bar{flex:1;min-width:120px;height:9px;border-radius:5px;overflow:hidden;
  background:linear-gradient(90deg,#E6F1FB,#EFEEE9 50%,#FCEBEB);position:relative;}
.re-press .bar i{display:block;height:100%;background:#B65F5A;opacity:.55;}
.re-press .nums b{font-weight:800;}
/* 신고가 카드(B안) — 헤더 + 지도 아이콘 + 평형별 1년 밴드 칩 */
.re-hi{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:12px;
  padding:11px 14px;margin-bottom:8px;
  transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease;}
.re-hi:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(52,53,47,.07);border-color:var(--sage,#A7BBA9);}
.re-hi.excl{opacity:.5;}
.re-hi-top{display:flex;align-items:flex-start;gap:11px;}
.re-hi-nm{font-weight:700;color:var(--ink,#34352f);font-size:14px;}
.re-hi-nm a{color:inherit;text-decoration:none;border-bottom:1px dashed #D6D8CF;}
.re-hi-nm a:hover{border-bottom-color:var(--sage,#A7BBA9);}
.re-hi-sub{font-size:11.5px;color:var(--muted,#9a9b92);margin-top:2px;}
.re-hi-map{flex:none;align-self:center;font-size:11px;font-weight:700;color:var(--sage-deep,#7E9A83);
  text-decoration:none;border:1px solid var(--line,#ECEDE7);border-radius:7px;padding:3px 9px;
  background:#fff;white-space:nowrap;}
.re-hi-map:hover{background:#EEF1EC;border-color:var(--sage,#A7BBA9);}
.re-hi-price{margin-left:auto;text-align:right;flex:none;}
.re-hi-price b{font-size:17px;font-weight:800;color:var(--ink,#34352f);letter-spacing:-.02em;}
.re-hi-price .tag{display:block;font-size:11px;font-weight:800;color:var(--up,#B65F5A);margin-top:2px;}
.re-hi-band{border-top:1px dashed #E4E5DE;margin-top:11px;padding-top:10px;}
.re-hi-bh{font-size:10.5px;font-weight:800;color:var(--muted,#9a9b92);letter-spacing:.02em;margin-bottom:9px;}
.re-hi-chips{display:flex;flex-wrap:wrap;gap:7px;}
.re-hi-chip{border:1px solid var(--line,#ECEDE7);border-radius:9px;padding:6px 10px;font-size:12px;
  font-weight:700;color:var(--ink,#34352f);background:var(--bg,#FCFCFA);}
.re-hi-chip.hl{border-color:#E7B7B4;background:#FCEBEB;color:#A32D2D;}
.re-hi-chip b{font-weight:800;}
.re-hi-chip small{color:var(--muted,#9a9b92);font-weight:600;margin-left:4px;}
.re-hi-chip.hl small{color:#B77;}
.re-hi-band-empty{font-size:11.5px;color:var(--muted,#9a9b92);}
@media(max-width:680px){.re-hi-top{flex-wrap:wrap;} .re-hi-map{order:3;margin-left:34px;}}
/* 주간 뷰(A안) — 지표별 스파크라인 */
.wk-wrap{background:var(--bg,#FCFCFA);border:1px solid var(--line,#ECEDE7);border-radius:12px;
  padding:4px 16px 8px;margin-bottom:8px;}
.wk-row{display:grid;grid-template-columns:78px 1fr 92px;align-items:center;gap:12px;
  padding:9px 0;border-bottom:1px solid #F1F2EC;}
.wk-row:last-child{border-bottom:none;}
.wk-row .k{font-size:12px;font-weight:700;color:#5d6258;}
.wk-row.hero .k{font-weight:800;color:var(--ink,#34352f);}
.wk-row .r{text-align:right;}
.wk-row .r b{font-size:15px;font-weight:800;letter-spacing:-.02em;}
.wk-row .r .d{display:block;font-size:10.5px;font-weight:700;margin-top:1px;}
.wk-spark{display:block;overflow:visible;}
.wk-spark-na{color:#b9bab2;font-size:12px;}
.wk-up{color:var(--up,#B65F5A);} .wk-dn{color:var(--down,#5A7CA0);}
.wk-sg{color:var(--sage-deep,#7E9A83);} .wk-mut{color:var(--muted,#9a9b92);}
/* 주목 단지 보드 */
.re-hotwrap{display:flex;flex-direction:column;gap:7px;margin-bottom:6px;}
.re-hot{display:flex;align-items:center;gap:11px;background:var(--card,#fff);
  border:1px solid var(--line,#ECEDE7);border-radius:12px;padding:10px 13px;}
.re-hot-rk{flex:none;width:22px;height:22px;border-radius:7px;background:#F2F5F0;color:#5d6258;
  font-size:12px;font-weight:800;display:flex;align-items:center;justify-content:center;}
.re-hot-r{text-align:right;min-width:70px;}
.re-hot-si{flex:none;width:78px;display:flex;align-items:center;gap:6px;}
.re-hot-si .bar{flex:1;height:8px;border-radius:4px;background:#EEF1EC;overflow:hidden;}
.re-hot-si .bar i{display:block;height:100%;background:var(--sage-deep,#7E9A83);}
.re-hot-si .v{font-size:11px;font-weight:800;color:#5d6258;width:22px;text-align:right;}
.re-hot-si.dim{color:#C4C6BD;font-size:12px;justify-content:center;}
/* 주목 단지 카드 (59/84·세대수·시공사·소재지·지도) */
.re-hcwrap{display:flex;flex-direction:column;gap:8px;margin-bottom:6px;}
.re-hc{display:flex;align-items:stretch;gap:11px;background:var(--card,#fff);
  border:1px solid var(--line,#ECEDE7);border-radius:14px;padding:12px 14px;}
.re-hc-rk{flex:none;width:23px;height:23px;border-radius:7px;background:#F2F5F0;color:#5d6258;
  font-size:12px;font-weight:800;display:flex;align-items:center;justify-content:center;margin-top:1px;}
.re-hc-main{flex:1;min-width:0;}
.re-hc-top{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;}
.re-hc-nm{font-size:14px;font-weight:800;color:var(--ink,#34352f);}
.re-hc-chg{font-size:12px;font-weight:800;}
.re-hc-chg.up{color:var(--up,#B65F5A);} .re-hc-chg.dn{color:var(--down,#5A7CA0);}
.re-hc-meta{font-size:11.5px;color:var(--muted,#9a9b92);margin-top:2px;}
.re-hc-stat{font-size:11.5px;color:var(--muted,#9a9b92);margin-top:3px;}
.re-hc-stat .up{color:var(--up,#B65F5A);} .re-hc-stat .dn{color:var(--down,#5A7CA0);}
.re-hc-stat .mut{color:#6f7068;} .re-hc-stat b{font-weight:800;}
.re-hc-prices{display:flex;align-items:center;gap:7px;margin-top:8px;flex-wrap:wrap;}
.re-hc-spk{display:inline-flex;align-items:center;gap:6px;margin-left:2px;}
.re-hc-spk .lab{font-size:9.5px;font-weight:700;color:#b3b4ab;}
.re-hc-pp{font-size:12.5px;font-weight:800;color:var(--ink,#34352f);background:#F7F8F4;
  border:1px solid var(--line,#ECEDE7);border-radius:8px;padding:4px 10px;}
.re-hc-pp i{font-style:normal;font-weight:700;color:var(--muted,#9a9b92);font-size:11px;margin-right:5px;}
.re-hc-pp.dim{color:#C4C6BD;background:#FAFAF7;} .re-hc-pp.dim i{color:#C4C6BD;}
.re-hc-jbox{display:flex;align-items:center;gap:11px;margin-top:9px;}
.re-hc-jg{flex:1;min-width:0;max-width:210px;}
.re-hc-jlab{display:flex;justify-content:space-between;font-size:10.5px;font-weight:700;
  color:var(--muted,#9a9b92);margin-bottom:4px;}
.re-hc-jlab b{color:var(--sage-deep,#7E9A83);font-weight:800;}
.re-hc-jbar{height:7px;border-radius:4px;background:#EBECE6;overflow:hidden;}
.re-hc-jbar i{display:block;height:100%;background:var(--sage,#A7BBA9);}
.re-hc-gap{font-size:12px;font-weight:600;color:#6f7068;white-space:nowrap;}
.re-hc-gap b{font-weight:800;color:var(--ink,#34352f);font-size:13px;}
.re-hc-map{flex:none;align-self:center;font-size:11.5px;font-weight:700;color:var(--sage-deep,#7E9A83);
  border:1px solid var(--line2,#DEDED7);border-radius:9px;padding:7px 11px;text-decoration:none;
  white-space:nowrap;transition:background .15s ease,border-color .15s ease;}
.re-hc-map:hover{background:#EEF1EC;border-color:var(--sage,#A7BBA9);}
@media(max-width:680px){.re-hc{flex-wrap:wrap;} .re-hc-map{margin-left:34px;margin-top:2px;}}
/* 가격지수 동향(연속/26년초대비) 섹션 */
.re-strk-sec{font-size:12px;font-weight:700;color:var(--ink,#34352f);margin:2px 2px 9px;letter-spacing:.02em;}
.re-strk-sec span{font-weight:500;color:var(--muted,#9a9b92);margin-left:6px;font-size:11px;}
.re-strk{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin:2px 0 16px;}
.re-strk-c{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:12px;padding:10px 12px;}
.re-strk-rg{font-size:13px;font-weight:800;color:var(--ink,#34352f);margin-bottom:5px;}
.re-strk-row{display:flex;align-items:center;gap:7px;font-size:11.5px;margin-top:4px;}
.re-strk-row .t{color:var(--muted,#9a9b92);width:26px;font-weight:600;}
.re-strk-bdg{font-weight:800;font-size:11px;border-radius:6px;padding:1px 7px;}
.re-strk-bdg.up{background:#FBEDEC;color:var(--up,#B65F5A);} .re-strk-bdg.dn{background:#EAF0F5;color:var(--down,#5A7CA0);} .re-strk-bdg.fl{background:#F0F1EC;color:var(--muted,#9a9b92);}
.re-strk-ytd{font-weight:800;margin-left:auto;} .re-strk-ytd.up{color:var(--up,#B65F5A);} .re-strk-ytd.dn{color:var(--down,#5A7CA0);} .re-strk-ytd.fl{color:var(--muted,#9a9b92);}
@media(max-width:680px){.re-strk{grid-template-columns:repeat(2,1fr);}}
.re-chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px;}
.re-chip{font-size:12px;color:var(--pill-ink,#5d6258);background:var(--pill-bg,#F1F2EC);
  border:1px solid var(--line,#ECEDE7);border-radius:999px;padding:4px 12px;}
.re-chip.on{background:var(--sage-deep,#7E9A83);color:#fff;border-color:var(--sage-deep,#7E9A83);}
.re-phase{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;background:var(--card,#fff);
  border:1px solid var(--line,#ECEDE7);border-radius:12px;padding:11px 15px;margin:2px 0 14px;}
.re-phase b{font-size:12px;color:var(--muted,#9a9b92);font-weight:600;margin-right:2px;}
.re-phase .seg{font-size:13px;font-weight:700;color:var(--ink,#34352f);}
.re-grp{font-size:12px;font-weight:700;color:var(--ink,#34352f);margin:16px 0 8px;letter-spacing:.02em;}
.re-grp .sub{font-weight:500;color:var(--muted,#9a9b92);font-size:11px;margin-left:6px;}
.re-delta{font-size:11px;font-weight:700;margin-left:7px;}
.re-delta.up{color:var(--up,#B65F5A);} .re-delta.dn{color:var(--down,#5A7CA0);} .re-delta.fl{color:var(--muted,#9a9b92);}
.re-base{font-size:10.5px;font-weight:500;color:var(--muted,#9a9b92);margin-left:6px;}
.re-sub-card{display:flex;align-items:flex-start;gap:11px;background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);
  border-radius:12px;padding:11px 14px;margin-bottom:8px;text-decoration:none;color:inherit;cursor:pointer;
  transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease;}
.re-sub-card:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(52,53,47,.07);border-color:var(--sage,#A7BBA9);}
.re-sub-go{align-self:center;margin-left:8px;color:#CFD1C8;font-size:13px;font-weight:800;flex:none;
  transition:color .15s ease,transform .15s ease;}
.re-sub-card:hover .re-sub-go{color:var(--sage-deep,#7E9A83);transform:translateX(2px);}
.re-sub-bdg{font-size:10.5px;font-weight:700;padding:2px 9px;border-radius:6px;flex:none;margin-top:1px;}
.re-sub-nm{font-weight:700;color:var(--ink,#34352f);}
.re-sub-meta{font-size:12px;color:var(--muted,#9a9b92);margin-top:2px;}
.re-sub-r{margin-left:auto;text-align:right;font-size:11.5px;color:var(--muted,#9a9b92);white-space:nowrap;padding-left:10px;}
.re-sub-r b{display:block;color:var(--ink,#34352f);font-size:12.5px;margin-bottom:1px;}
.re-hl-sec{font-size:12px;font-weight:700;color:var(--ink,#34352f);margin:6px 2px 8px;letter-spacing:.02em;}
.re-hl-sec span{font-weight:500;color:var(--muted,#9a9b92);margin-left:6px;}
.re-hl{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:2px 0 14px;}
.re-hl-card{position:relative;background:linear-gradient(180deg,#FBF6EE,#fff);border:1px solid #EBE2D2;
  border-radius:14px;padding:12px 14px;display:block;text-decoration:none;color:inherit;cursor:pointer;
  transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease;}
.re-hl-card:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(138,109,59,.13);border-color:#D8C49A;}
.re-sub-card,.re-sub-card:link,.re-sub-card:visited,.re-hl-card,.re-hl-card:link,.re-hl-card:visited{color:var(--ink,#34352f) !important;text-decoration:none !important;}
.re-sub-card *,.re-hl-card *{text-decoration:none !important;}
.re-hl-go{position:absolute;right:12px;bottom:11px;color:#C9B78F;font-size:13px;font-weight:800;
  transition:color .15s ease,transform .15s ease;}
.re-hl-card:hover .re-hl-go{color:#8A6D3B;transform:translateX(2px);}
.re-hl-dday{position:absolute;top:11px;right:12px;background:var(--up,#B65F5A);color:#fff;
  font-size:11px;font-weight:800;border-radius:7px;padding:2px 8px;}
.re-hl-nm{font-size:14px;font-weight:800;color:var(--ink,#34352f);margin-bottom:2px;padding-right:62px;}
.re-hl-meta{font-size:11.5px;color:var(--muted,#9a9b92);line-height:1.5;}
.re-hl-when{font-size:12px;font-weight:700;color:#8A6D3B;margin-top:7px;}
.re-tl{display:flex;overflow-x:auto;background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);
  border-radius:14px;padding:4px 2px;margin:2px 0 14px;}
.re-tl-col{flex:1;min-width:80px;text-align:center;padding:9px 6px;border-right:1px dashed var(--line,#ECEDE7);}
.re-tl-col:last-child{border-right:none;}
.re-tl-d{font-size:11px;color:var(--muted,#9a9b92);font-weight:700;}
.re-tl-dot{margin:7px auto 5px;width:8px;height:8px;border-radius:50%;background:var(--line2,#DEDED7);}
.re-tl-dot.s{background:var(--sage-deep,#7E9A83);} .re-tl-dot.e{background:var(--up,#B65F5A);}
.re-tl-c{font-size:10.5px;color:var(--ink,#34352f);line-height:1.3;}
.re-sub-when{font-size:11.5px;color:var(--muted,#9a9b92);margin-top:3px;}
.re-sub-acts{display:flex;flex-direction:column;gap:5px;flex:none;align-self:center;padding-left:8px;}
.re-hl-acts{display:flex;gap:6px;margin-top:9px;}
.re-go-btn{font-size:11px;font-weight:700;color:var(--sage-deep,#7E9A83);border:1px solid var(--line2,#DEDED7);
  border-radius:8px;padding:5px 10px;text-decoration:none !important;white-space:nowrap;background:var(--card,#fff);
  transition:background .15s ease,border-color .15s ease;display:inline-block;text-align:center;}
.re-go-btn:hover{background:#EEF1EC;border-color:var(--sage,#A7BBA9);}
.re-go-btn.map{color:#5d6258;}
.re-go-btn.gold{border-color:#E2D3B0;color:#8A6D3B;background:rgba(255,255,255,.65);}
.re-go-btn.gold:hover{background:#fff;border-color:#D8C49A;}
.nv{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;flex:none;
  border-radius:4px;background:#03C75A;color:#fff;font-size:10px;font-weight:900;
  text-decoration:none;margin-left:5px;vertical-align:1px;line-height:1;}
.nv:hover{filter:brightness(.92);}
@media(max-width:680px){.re-hl{grid-template-columns:1fr;}}
/* 주목 지역 밴드 (지도 위 · 5개 권역 구 통합 · 월간 전월대비) */
.re-wb-sec{font-size:12px;font-weight:700;color:var(--ink,#34352f);margin:2px 2px 9px;letter-spacing:.02em;}
.re-wb-sec span{font-weight:500;color:var(--muted,#9a9b92);margin-left:6px;font-size:11px;}
.re-wb{display:grid;grid-template-columns:repeat(auto-fit,minmax(205px,1fr));gap:9px;margin:2px 0 6px;}
.re-wb-c{background:var(--card,#fff);border:1px solid var(--line,#ECEDE7);border-radius:12px;padding:10px 12px;}
.re-wb-h{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--muted,#9a9b92);font-weight:600;margin-bottom:7px;}
.re-wb-h .dot{width:8px;height:8px;border-radius:2px;flex:none;}
.re-wb-h .sub{font-weight:500;font-size:9.5px;}
.re-wb-r{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-top:4px;}
.re-wb-r.lead{margin-top:0;}
.re-wb-r .rg{color:var(--ink,#34352f);font-size:12px;font-weight:700;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.re-wb-r .rg em{font-style:normal;font-weight:500;color:var(--muted,#9a9b92);margin-right:3px;}
.re-wb-r.sub2 .rg{font-size:11.5px;font-weight:500;color:#5b5c54;}
.re-wb-r .v{font-weight:800;font-size:14px;letter-spacing:-.01em;flex:none;}
.re-wb-r.sub2 .v{font-size:11.5px;font-weight:700;}
.re-wb-r .v.up{color:var(--up,#B65F5A);} .re-wb-r .v.dn{color:var(--down,#5A7CA0);} .re-wb-r .v.sg{color:var(--sage-deep,#7E9A83);}
.re-wb-pill{font-size:10px;font-weight:800;padding:1px 7px;border-radius:999px;flex:none;}
.re-wb-pill.up{background:#FBEDEC;color:var(--up,#B65F5A);} .re-wb-pill.dn{background:#EAF0F5;color:var(--down,#5A7CA0);}
.re-wb-gap{font-size:9.5px;color:var(--muted,#9a9b92);margin:1px 0 3px;}
.re-wb-foot{font-size:10px;color:var(--muted,#9a9b92);margin:0 2px 16px;line-height:1.5;}
@media(max-width:680px){.re-wb{grid-template-columns:repeat(2,1fr);}}
</style>
"""


def _spark_svg(series, col, kind, baseline=None):
    w, h = 240, 46
    lo, hi = min(series), max(series)
    if baseline is not None:
        lo, hi = min(lo, baseline), max(hi, baseline)
    rng = (hi - lo) or 1

    def y(v):
        return h - 4 - (v - lo) / rng * (h - 8)

    if kind == "bar":
        mx = max(series) or 1
        bw = w / len(series)
        rects = "".join(
            f'<rect x="{i*bw+1:.1f}" y="{h-(v/mx)*(h-6):.1f}" '
            f'width="{bw-3:.1f}" height="{(v/mx)*(h-6):.1f}" fill="{col}" '
            f'opacity="{1 if i == len(series)-1 else 0.5:.1f}" rx="1"/>'
            for i, v in enumerate(series))
        return f'<svg class="re-spark" viewBox="0 0 {w} {h}">{rects}</svg>'

    pts = " ".join(f"{i/(len(series)-1)*w:.1f},{y(v):.1f}" for i, v in enumerate(series))
    base = ""
    if baseline is not None:
        by = y(baseline)
        base = (f'<line x1="0" y1="{by:.1f}" x2="{w}" y2="{by:.1f}" '
                f'stroke="#C9CBC2" stroke-width="1" stroke-dasharray="3 3"/>')
    dot = f'<circle cx="{w}" cy="{y(series[-1]):.1f}" r="2.6" fill="{col}"/>'
    return (f'<svg class="re-spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
            f'{base}<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2"/>'
            f'{dot}</svg>')


# ── 지도 컴포넌트(iframe) HTML 생성 ─────────────────────────────
# ── 지방 광역시(인천·부산·대구) placeholder 지오메트리 + 샘플 ──────────────
#   실제 구/군 경계가 없어 2x2 타일(주요 3구 + 이외)로 예시 배치. 타일 n은 엔진 _local
#   구명과 일치(연수구/서구/남동구 등) → 런타임 지표 머지. 실데이터 확보 시 경계 교체.
_LOCAL_GEO = json.loads(r"""{"incheon":[{"n":"중구","sl":"중","d":"M813.3,1387.4 L815.0,1385.6 L812.6,1374.1 L802.5,1355.5 L789.2,1347.5 L785.4,1355.2 L779.4,1360.1 L776.6,1358.9 L776.0,1355.9 L784.3,1345.0 L778.2,1336.6 L767.2,1329.5 L747.4,1342.9 L738.5,1345.0 L742.0,1353.6 L739.4,1356.0 L731.3,1340.2 L706.7,1338.8 L714.6,1332.9 L719.3,1334.2 L721.5,1326.4 L718.6,1323.8 L714.9,1304.2 L700.5,1301.2 L692.9,1290.8 L689.8,1278.3 L691.3,1273.1 L698.0,1263.8 L706.8,1260.6 L726.7,1266.5 L812.2,1207.2 L878.4,1200.4 L920.0,1202.1 L958.7,1182.0 L964.1,1168.1 L961.0,1167.1 L964.3,1137.4 L967.8,1127.5 L975.4,1122.2 L973.5,1117.1 L976.5,1124.0 L976.2,1126.1 L994.1,1118.5 L1003.6,1119.0 L1004.6,1124.8 L1014.5,1126.8 L1020.3,1134.5 L1019.1,1140.2 L1042.8,1145.0 L1062.1,1157.8 L1073.8,1156.8 L1094.9,1164.5 L1105.3,1181.1 L1120.3,1191.3 L1127.1,1215.8 L1131.3,1220.8 L1130.8,1225.9 L1119.0,1229.1 L1098.8,1248.1 L1068.4,1256.7 L1037.7,1259.4 L983.1,1282.3 L957.6,1307.1 L942.5,1333.3 L859.9,1389.6 L829.8,1385.4 L813.3,1387.4 Z","cx":915.3,"cy":1252.4},{"n":"동구","sl":"동","d":"M1235.5,1209.8 L1244.1,1210.2 L1289.8,1240.6 L1309.5,1255.3 L1309.4,1258.5 L1271.7,1238.3 L1267.9,1243.8 L1270.4,1251.7 L1264.7,1262.3 L1267.1,1264.2 L1267.5,1271.3 L1253.2,1272.1 L1247.8,1276.1 L1218.5,1249.0 L1210.1,1244.5 L1204.7,1246.3 L1197.7,1239.5 L1203.2,1233.9 L1187.6,1239.6 L1184.1,1230.3 L1216.1,1217.9 L1226.7,1230.2 L1239.8,1239.4 L1238.3,1242.5 L1240.1,1239.1 L1218.3,1216.0 L1235.5,1209.8 Z","cx":1234.9,"cy":1243.1},{"n":"미추홀구","sl":"미추홀","d":"M1308.9,1258.4 L1330.1,1265.8 L1331.5,1268.2 L1328.8,1273.2 L1334.4,1274.4 L1333.5,1281.2 L1344.9,1282.3 L1353.8,1292.9 L1348.8,1299.2 L1348.1,1316.9 L1345.0,1316.7 L1346.0,1328.0 L1364.9,1336.3 L1363.4,1346.0 L1350.1,1347.3 L1354.8,1359.4 L1338.1,1360.0 L1331.1,1367.5 L1314.9,1364.6 L1312.2,1367.1 L1282.0,1355.1 L1272.9,1355.0 L1256.4,1356.8 L1251.5,1363.5 L1239.8,1367.1 L1230.0,1363.1 L1227.8,1368.1 L1221.0,1323.2 L1223.4,1320.1 L1222.0,1314.4 L1228.5,1311.3 L1243.1,1286.2 L1247.0,1283.8 L1247.8,1276.1 L1253.2,1272.1 L1267.5,1271.3 L1267.1,1264.2 L1264.7,1262.3 L1270.4,1251.7 L1267.9,1243.8 L1271.7,1238.3 L1308.9,1258.4 Z","cx":1290.3,"cy":1305.2},{"n":"연수구","sl":"연수","d":"M1161.5,1401.4 L1167.0,1400.7 L1168.0,1390.3 L1174.4,1379.3 L1180.7,1375.6 L1228.7,1375.4 L1232.2,1396.6 L1236.5,1394.5 L1237.5,1389.2 L1233.2,1385.9 L1234.8,1378.4 L1229.8,1363.4 L1239.8,1367.1 L1250.6,1364.1 L1258.5,1356.1 L1282.0,1355.1 L1305.1,1365.4 L1331.1,1367.5 L1338.1,1360.0 L1354.8,1359.4 L1350.1,1347.3 L1363.8,1345.5 L1368.8,1346.5 L1372.0,1357.7 L1367.0,1380.2 L1333.8,1414.8 L1328.6,1428.7 L1316.6,1436.2 L1294.8,1458.7 L1307.1,1466.4 L1326.3,1470.8 L1328.0,1476.9 L1350.7,1480.4 L1290.4,1560.0 L1271.6,1566.3 L1246.6,1567.1 L1246.6,1574.0 L1264.9,1573.2 L1270.0,1575.3 L1249.7,1573.9 L1244.4,1575.5 L1243.7,1579.1 L1209.2,1579.7 L1208.8,1576.6 L1194.0,1576.7 L1193.4,1566.5 L1191.0,1566.3 L1191.2,1575.5 L1184.0,1575.7 L1181.1,1587.6 L1184.9,1590.1 L1176.1,1590.4 L1179.9,1588.0 L1183.1,1575.7 L1155.2,1576.0 L1150.3,1586.4 L1153.3,1590.5 L1127.4,1590.4 L1127.4,1585.8 L1147.6,1585.4 L1157.7,1566.6 L1131.9,1566.7 L1131.8,1548.4 L1240.7,1548.0 L1207.6,1548.8 L1205.4,1550.3 L1205.5,1565.6 L1245.4,1565.4 L1256.3,1562.6 L1265.0,1553.1 L1259.8,1548.3 L1248.0,1548.0 L1260.0,1547.9 L1265.7,1552.2 L1270.7,1545.8 L1196.4,1489.2 L1184.2,1470.9 L1184.1,1457.0 L1180.7,1454.4 L1180.7,1445.7 L1184.1,1443.0 L1183.9,1401.1 L1161.5,1401.4 Z","cx":1250.4,"cy":1468.6},{"n":"남동구","sl":"남동","d":"M1401.8,1271.7 L1419.2,1264.8 L1440.4,1273.5 L1448.6,1284.6 L1454.2,1282.1 L1461.4,1284.5 L1469.9,1274.2 L1487.4,1272.7 L1490.7,1267.8 L1499.2,1266.4 L1511.0,1267.7 L1514.1,1282.0 L1510.7,1303.2 L1515.3,1308.1 L1512.6,1317.5 L1502.3,1318.8 L1496.4,1323.7 L1497.2,1328.6 L1492.6,1336.4 L1497.4,1352.4 L1496.8,1365.9 L1493.5,1374.0 L1484.4,1377.5 L1475.6,1376.5 L1462.5,1385.5 L1466.0,1396.9 L1461.5,1400.5 L1459.3,1413.9 L1453.4,1422.2 L1443.5,1427.8 L1444.9,1433.9 L1435.2,1446.9 L1430.3,1448.4 L1400.4,1482.1 L1392.2,1485.3 L1333.3,1472.4 L1329.1,1474.2 L1294.8,1458.7 L1316.6,1436.2 L1328.6,1428.7 L1333.8,1414.8 L1356.5,1393.2 L1369.4,1374.6 L1372.0,1357.7 L1368.8,1346.5 L1363.8,1345.5 L1364.9,1336.3 L1346.0,1328.0 L1345.0,1316.7 L1348.1,1316.9 L1348.8,1299.2 L1353.8,1292.9 L1344.9,1282.3 L1333.5,1281.2 L1334.4,1274.4 L1328.8,1273.2 L1332.4,1266.5 L1354.4,1276.5 L1365.5,1277.6 L1374.6,1273.6 L1380.3,1248.2 L1382.1,1254.3 L1392.5,1258.6 L1401.8,1271.7 Z","cx":1432.6,"cy":1370.0},{"n":"부평구","sl":"부평","d":"M1476.2,1142.2 L1476.8,1152.7 L1472.0,1162.1 L1462.9,1159.5 L1456.3,1165.9 L1448.3,1163.5 L1440.0,1178.8 L1444.1,1196.1 L1440.3,1213.2 L1441.5,1231.4 L1467.0,1241.1 L1468.1,1248.3 L1474.0,1255.4 L1489.4,1263.2 L1490.6,1268.5 L1487.4,1272.7 L1469.9,1274.2 L1463.2,1283.9 L1454.2,1282.1 L1448.6,1284.6 L1440.4,1273.5 L1419.2,1264.8 L1409.7,1271.8 L1401.8,1271.7 L1392.7,1258.8 L1382.1,1254.3 L1380.3,1248.2 L1374.6,1273.6 L1365.5,1277.6 L1336.7,1270.0 L1328.5,1263.5 L1341.1,1250.1 L1339.9,1240.4 L1344.3,1235.8 L1358.4,1235.0 L1354.3,1223.1 L1348.8,1217.2 L1343.6,1218.1 L1345.1,1211.1 L1337.7,1203.4 L1343.9,1196.0 L1337.0,1187.5 L1332.9,1170.0 L1326.7,1165.1 L1326.7,1159.1 L1333.9,1146.4 L1338.2,1143.4 L1476.2,1142.2 Z","cx":1392.3,"cy":1215.2},{"n":"계양구","sl":"계양","d":"M1430.8,976.5 L1445.2,978.0 L1455.7,1004.5 L1460.5,1008.7 L1467.3,1007.2 L1467.2,1001.1 L1471.7,995.2 L1481.8,996.1 L1490.5,988.2 L1500.4,995.8 L1522.5,1001.8 L1528.2,994.6 L1541.1,1004.2 L1538.2,1007.6 L1536.5,1005.1 L1529.2,1018.6 L1519.2,1023.3 L1517.1,1034.6 L1506.6,1043.5 L1510.3,1056.2 L1506.2,1051.3 L1496.4,1062.7 L1484.4,1067.1 L1487.7,1071.5 L1480.2,1105.2 L1477.3,1106.3 L1476.2,1142.2 L1338.2,1143.4 L1333.7,1126.4 L1326.0,1125.1 L1327.3,1115.6 L1342.9,1113.3 L1344.9,1101.3 L1349.1,1099.5 L1354.8,1099.0 L1358.5,1102.6 L1371.5,1099.4 L1382.5,1073.8 L1370.4,1063.6 L1363.4,1064.8 L1358.5,1059.3 L1363.7,1054.5 L1365.5,1046.0 L1359.5,1043.4 L1356.2,1037.5 L1360.4,1027.5 L1341.3,1019.6 L1338.0,1014.7 L1331.8,1017.6 L1326.2,1014.6 L1322.4,1007.9 L1324.0,999.2 L1332.3,998.3 L1385.4,1013.7 L1393.2,1005.1 L1394.5,990.1 L1402.4,982.4 L1417.2,978.7 L1429.5,982.8 L1430.8,976.5 Z","cx":1429.0,"cy":1061.0},{"n":"서구","sl":"서","d":"M1408.6,979.5 L1394.5,990.1 L1393.2,1005.1 L1385.4,1013.7 L1332.3,998.3 L1324.0,999.4 L1322.4,1007.9 L1326.2,1014.6 L1331.8,1017.6 L1338.0,1014.7 L1341.3,1019.6 L1360.4,1027.5 L1356.2,1037.5 L1359.5,1043.4 L1365.5,1046.0 L1363.7,1054.5 L1358.5,1059.3 L1363.4,1064.8 L1370.4,1063.6 L1382.5,1073.8 L1371.5,1099.4 L1358.5,1102.6 L1354.8,1099.0 L1344.9,1101.3 L1342.9,1113.3 L1329.0,1114.5 L1325.2,1122.6 L1333.7,1126.4 L1338.2,1143.4 L1332.3,1147.8 L1326.6,1162.1 L1332.9,1170.0 L1337.0,1187.5 L1343.9,1196.0 L1337.7,1203.4 L1345.1,1211.1 L1343.6,1218.1 L1348.8,1217.2 L1354.3,1223.1 L1358.4,1235.0 L1346.5,1235.0 L1339.9,1240.4 L1341.1,1250.1 L1328.5,1263.5 L1332.4,1266.5 L1331.5,1268.2 L1327.0,1263.8 L1309.4,1258.5 L1309.5,1255.3 L1289.8,1240.6 L1242.7,1210.6 L1241.6,1189.9 L1224.8,1189.8 L1224.7,1198.9 L1209.2,1209.0 L1173.8,1209.9 L1174.0,1172.1 L1168.9,1160.8 L1169.9,1120.3 L1162.9,1120.4 L1158.3,1083.3 L1178.6,1069.3 L1167.2,1059.5 L1167.1,1052.4 L1150.0,1053.8 L1142.9,1046.5 L1139.0,1040.0 L1143.2,1032.4 L1116.1,988.0 L1148.9,977.6 L1172.0,962.4 L1183.4,949.1 L1192.9,944.9 L1197.8,951.5 L1215.0,953.8 L1227.3,924.0 L1227.4,917.7 L1236.0,910.8 L1237.2,895.9 L1251.7,891.6 L1256.5,894.1 L1265.5,872.5 L1269.9,868.3 L1305.6,878.8 L1310.0,888.3 L1318.6,889.0 L1326.9,899.8 L1348.4,911.2 L1360.9,925.7 L1369.7,931.1 L1371.0,941.6 L1366.9,948.8 L1368.2,954.1 L1377.8,947.7 L1386.5,950.7 L1390.9,961.4 L1408.6,979.5 Z","cx":1275.2,"cy":1067.0}],"busan":[{"n":"중구","sl":"중","d":"M5888.7,6921.2 L5898.5,6931.2 L5905.7,6933.7 L5904.8,6939.1 L5910.4,6941.7 L5911.6,6945.5 L5915.8,6943.8 L5909.8,6948.1 L5903.2,6943.1 L5902.2,6946.0 L5909.6,6951.9 L5906.8,6955.3 L5899.1,6949.5 L5898.5,6953.6 L5902.4,6959.2 L5897.5,6968.0 L5876.2,6970.4 L5866.7,6955.3 L5868.3,6941.9 L5875.4,6934.0 L5878.5,6935.5 L5878.2,6922.7 L5888.7,6921.2 Z","cx":5885.1,"cy":6945.8},{"n":"서구","sl":"서","d":"M5817.2,6863.0 L5841.8,6865.5 L5855.8,6873.5 L5866.7,6871.7 L5874.7,6874.4 L5875.4,6900.2 L5872.1,6914.9 L5879.5,6928.6 L5878.5,6935.5 L5875.4,6934.0 L5869.4,6938.6 L5866.1,6952.2 L5876.2,6970.4 L5873.9,6975.6 L5876.8,6995.3 L5872.7,7016.8 L5864.1,7015.2 L5857.7,7021.7 L5866.3,7032.8 L5868.3,7051.5 L5856.9,7062.7 L5855.3,7072.3 L5845.5,7075.9 L5847.5,7074.1 L5842.1,7054.9 L5846.5,7048.7 L5835.6,7029.4 L5833.6,7011.7 L5840.3,7011.3 L5846.6,7015.7 L5852.5,6975.0 L5846.6,6966.0 L5839.0,6961.1 L5845.3,6946.3 L5833.3,6935.4 L5832.5,6928.5 L5828.8,6925.8 L5830.2,6918.6 L5822.6,6912.5 L5824.9,6903.1 L5831.8,6896.5 L5830.2,6879.0 L5833.3,6872.6 L5817.2,6863.0 Z","cx":5861.5,"cy":6968.2},{"n":"동구","sl":"동","d":"M5915.0,6850.4 L5926.9,6859.0 L5950.2,6860.6 L5953.2,6871.3 L5953.3,6887.2 L5950.7,6894.8 L5933.8,6916.7 L5926.6,6910.8 L5932.3,6905.0 L5932.4,6899.2 L5927.2,6898.3 L5922.1,6903.4 L5919.4,6910.3 L5932.3,6921.6 L5930.5,6924.1 L5922.2,6917.7 L5916.7,6920.2 L5923.5,6926.3 L5923.5,6930.1 L5915.3,6941.1 L5910.4,6941.7 L5904.8,6939.1 L5905.7,6933.7 L5898.5,6931.2 L5888.7,6921.2 L5878.2,6922.7 L5872.8,6917.1 L5875.4,6900.2 L5874.7,6874.4 L5890.1,6870.8 L5899.4,6864.7 L5901.0,6853.8 L5904.8,6849.2 L5915.0,6850.4 Z","cx":5912.3,"cy":6896.5},{"n":"영도구","sl":"영도","d":"M5946.1,6950.4 L5944.2,6965.0 L5957.9,6969.8 L5973.3,6989.4 L5977.2,6990.8 L5979.0,6996.6 L5975.9,6999.3 L5978.8,7003.1 L5985.5,6999.3 L5986.5,6994.2 L5986.4,7000.0 L5978.8,7004.4 L5986.9,7019.6 L5991.3,7020.6 L6004.6,7007.3 L6011.3,7007.1 L6008.8,7016.4 L6001.2,7022.8 L5993.6,7025.6 L5991.6,7022.1 L5980.2,7028.7 L5982.4,7032.5 L5988.5,7032.6 L5995.6,7049.6 L6010.6,7056.0 L6010.5,7060.7 L6004.0,7070.8 L6005.7,7074.4 L6002.6,7077.6 L5992.7,7081.8 L5985.6,7078.9 L5981.7,7064.8 L5974.8,7055.0 L5969.3,7054.6 L5962.3,7059.3 L5959.8,7054.7 L5950.7,7052.1 L5951.1,7035.9 L5935.5,7033.3 L5902.5,7006.8 L5891.7,6996.0 L5885.6,6978.6 L5886.3,6974.3 L5896.2,6977.7 L5894.9,6973.2 L5899.7,6975.4 L5902.6,6970.7 L5910.8,6967.3 L5919.9,6971.2 L5917.7,6965.0 L5921.1,6963.8 L5926.1,6968.1 L5924.2,6960.9 L5940.1,6957.5 L5946.1,6950.4 Z","cx":5945.8,"cy":7011.9},{"n":"부산진구","sl":"부산진","d":"M5910.6,6721.3 L5918.6,6733.2 L5917.3,6742.9 L5924.5,6756.3 L5944.4,6759.6 L5946.9,6774.5 L5961.3,6778.1 L5964.7,6769.0 L5983.8,6787.5 L5982.6,6797.8 L5976.6,6805.5 L5985.8,6820.4 L5984.2,6826.8 L5977.7,6838.7 L5970.6,6838.6 L5962.3,6844.4 L5947.3,6843.1 L5950.2,6860.6 L5926.9,6859.0 L5915.0,6850.4 L5904.9,6849.2 L5901.0,6853.8 L5899.4,6864.7 L5890.1,6870.8 L5874.7,6874.4 L5849.6,6871.2 L5856.5,6856.0 L5852.4,6849.9 L5856.6,6846.5 L5857.3,6833.3 L5854.9,6824.9 L5845.5,6819.0 L5850.0,6800.3 L5845.5,6783.4 L5862.3,6766.9 L5865.8,6750.1 L5874.6,6739.8 L5874.5,6734.2 L5880.8,6733.5 L5895.4,6722.0 L5910.6,6721.3 Z","cx":5915.6,"cy":6799.1},{"n":"동래구","sl":"동래","d":"M5976.9,6658.5 L5994.4,6667.5 L5987.9,6678.7 L5996.4,6677.6 L6029.0,6695.3 L6039.0,6695.6 L6040.7,6708.6 L6045.8,6716.3 L6050.2,6717.3 L6046.9,6732.6 L6048.4,6759.2 L6041.9,6746.7 L5994.6,6735.2 L5986.5,6730.2 L5981.3,6721.6 L5969.0,6724.6 L5964.5,6731.4 L5949.9,6735.1 L5945.9,6740.0 L5927.3,6738.6 L5918.6,6733.2 L5910.6,6721.3 L5910.8,6715.9 L5922.8,6702.7 L5924.4,6688.8 L5933.3,6677.5 L5939.3,6660.5 L5944.9,6658.0 L5957.6,6660.5 L5976.9,6658.5 Z","cx":5980.2,"cy":6705.7},{"n":"남구","sl":"남","d":"M6010.2,6812.8 L6021.5,6835.6 L6025.7,6852.5 L6023.3,6857.5 L6040.9,6874.2 L6046.4,6874.1 L6041.2,6875.1 L6036.4,6881.2 L6044.1,6875.8 L6053.7,6882.9 L6051.8,6888.0 L6044.8,6897.1 L6043.9,6900.1 L6058.9,6878.7 L6062.6,6883.0 L6062.7,6895.4 L6065.9,6903.3 L6075.4,6916.4 L6071.8,6927.5 L6073.7,6932.0 L6071.9,6940.0 L6065.0,6955.3 L6067.4,6958.4 L6066.1,6961.4 L6049.2,6959.5 L6044.3,6952.9 L6039.5,6957.3 L6047.3,6965.1 L6037.4,6980.3 L6046.3,6965.2 L6039.7,6958.4 L6023.5,6973.2 L6029.0,6979.3 L6018.4,6981.2 L6009.8,6974.7 L6005.4,6937.7 L6000.4,6939.1 L6000.4,6951.3 L5970.5,6951.3 L5952.1,6938.0 L5955.8,6940.3 L5959.9,6933.7 L5957.7,6930.1 L5959.9,6926.4 L5968.2,6919.8 L5965.2,6914.9 L5962.8,6918.2 L5959.9,6916.1 L5966.7,6906.8 L5951.8,6905.1 L5953.2,6871.3 L5947.8,6855.9 L5947.3,6843.1 L5962.3,6844.4 L5970.6,6838.6 L5977.7,6838.7 L5985.8,6820.4 L5997.9,6814.3 L6005.3,6816.0 L6010.2,6812.8 Z","cx":5998.8,"cy":6896.2},{"n":"북구","sl":"북","d":"M5892.6,6537.0 L5917.1,6541.9 L5908.3,6555.2 L5907.2,6566.5 L5895.9,6574.3 L5915.7,6582.9 L5919.2,6587.4 L5913.0,6596.3 L5913.4,6606.5 L5921.2,6611.6 L5922.7,6621.0 L5910.4,6641.4 L5911.0,6646.3 L5926.2,6652.6 L5935.4,6652.7 L5942.3,6648.4 L5944.9,6658.0 L5939.3,6660.5 L5933.3,6677.5 L5924.4,6688.8 L5922.8,6702.7 L5910.8,6715.9 L5910.6,6721.3 L5895.4,6722.0 L5880.8,6733.5 L5874.5,6734.2 L5874.6,6739.8 L5865.9,6750.1 L5826.8,6744.0 L5825.5,6739.5 L5812.9,6731.2 L5807.3,6734.8 L5801.4,6729.8 L5803.8,6719.7 L5801.1,6716.5 L5811.7,6703.8 L5815.9,6689.5 L5821.5,6641.0 L5818.6,6633.4 L5850.4,6560.3 L5853.7,6550.7 L5851.1,6543.0 L5866.7,6537.4 L5892.6,6537.0 Z","cx":5865.9,"cy":6643.9},{"n":"해운대구","sl":"해운대","d":"M6126.0,6631.5 L6137.4,6634.7 L6153.2,6653.3 L6145.1,6683.6 L6136.3,6691.4 L6135.8,6704.6 L6154.3,6717.6 L6159.2,6714.7 L6172.8,6724.8 L6182.7,6726.7 L6185.0,6730.9 L6180.6,6743.9 L6183.7,6745.2 L6193.4,6743.1 L6205.2,6722.7 L6214.0,6721.4 L6226.7,6727.6 L6226.7,6755.7 L6229.6,6763.2 L6215.8,6768.8 L6210.2,6775.6 L6207.0,6804.2 L6202.4,6815.5 L6188.5,6817.3 L6177.8,6828.4 L6169.9,6828.2 L6151.9,6818.1 L6128.8,6822.6 L6121.3,6835.8 L6115.5,6835.0 L6118.0,6825.5 L6122.5,6820.7 L6112.6,6824.9 L6109.7,6831.8 L6101.3,6829.0 L6097.8,6823.2 L6100.7,6819.4 L6094.6,6812.8 L6084.9,6810.2 L6079.1,6812.9 L6069.6,6803.2 L6056.2,6775.3 L6047.7,6748.8 L6046.9,6732.6 L6050.2,6717.3 L6045.8,6716.3 L6040.7,6708.6 L6039.0,6695.6 L6042.8,6690.0 L6056.3,6685.3 L6052.0,6668.3 L6053.1,6662.4 L6071.5,6654.9 L6078.3,6644.9 L6079.3,6635.2 L6088.3,6632.7 L6097.8,6620.1 L6105.7,6597.7 L6113.8,6606.4 L6113.5,6609.5 L6128.5,6613.8 L6126.0,6631.5 Z","cx":6100.6,"cy":6716.8},{"n":"사하구","sl":"사하","d":"M5747.3,7085.7 L5733.0,7027.2 L5741.2,7025.4 L5732.9,7026.7 L5728.5,7003.7 L5737.2,6975.7 L5739.6,6944.5 L5725.6,6942.9 L5723.0,6962.6 L5714.4,6992.7 L5694.2,7022.4 L5687.9,7022.7 L5686.1,7011.8 L5692.6,6996.6 L5694.8,6963.9 L5701.2,6944.7 L5706.4,6940.8 L5699.2,6936.1 L5698.5,6931.4 L5712.4,6914.2 L5723.5,6905.5 L5740.9,6875.7 L5751.6,6871.6 L5742.3,6901.7 L5744.2,6915.3 L5746.2,6917.5 L5754.4,6907.4 L5778.1,6919.1 L5786.2,6918.9 L5799.6,6901.9 L5824.4,6904.2 L5822.6,6912.5 L5830.2,6918.6 L5828.8,6925.8 L5832.5,6928.5 L5831.8,6933.0 L5845.3,6946.3 L5839.0,6961.1 L5846.6,6966.0 L5852.5,6975.0 L5852.8,6981.5 L5846.6,7015.7 L5840.3,7011.3 L5833.6,7011.7 L5835.1,6997.4 L5831.8,6993.3 L5824.9,6999.4 L5827.3,7008.4 L5821.6,7006.9 L5819.7,7000.6 L5811.5,6998.5 L5810.6,7007.6 L5815.1,7018.2 L5815.9,7047.9 L5820.4,7062.2 L5827.7,7083.9 L5838.5,7082.5 L5825.0,7085.8 L5822.1,7093.4 L5810.4,7091.5 L5810.1,7081.6 L5802.3,7060.9 L5795.0,7056.5 L5781.0,7063.9 L5772.1,7063.5 L5771.3,7069.3 L5773.8,7072.0 L5791.4,7076.6 L5785.8,7085.4 L5772.5,7081.8 L5766.2,7086.2 L5766.2,7092.2 L5782.2,7103.5 L5772.6,7101.8 L5761.2,7113.0 L5761.7,7120.0 L5758.1,7122.1 L5755.9,7112.4 L5760.2,7106.2 L5762.1,7095.0 L5747.3,7085.7 Z","cx":5779.1,"cy":6997.0},{"n":"금정구","sl":"금정","d":"M6029.9,6464.3 L6076.4,6484.1 L6079.3,6495.7 L6066.1,6525.0 L6069.6,6531.6 L6059.3,6558.6 L6061.9,6571.4 L6083.8,6574.5 L6086.0,6577.7 L6095.3,6574.7 L6093.5,6589.7 L6105.7,6597.7 L6097.8,6620.1 L6088.3,6632.7 L6079.3,6635.2 L6078.3,6644.9 L6071.5,6654.9 L6053.1,6662.4 L6052.0,6668.3 L6056.3,6685.3 L6042.8,6690.0 L6039.0,6695.6 L6029.0,6695.3 L6003.8,6680.2 L5987.9,6678.7 L5994.4,6667.5 L5984.2,6661.6 L5983.1,6664.0 L5976.7,6658.1 L5946.9,6659.9 L5942.3,6648.4 L5935.4,6652.7 L5926.2,6652.6 L5911.0,6646.3 L5910.4,6641.4 L5922.7,6621.0 L5921.2,6611.6 L5913.4,6606.5 L5913.0,6596.3 L5919.2,6587.4 L5915.7,6582.9 L5895.9,6574.3 L5907.2,6566.5 L5908.3,6555.2 L5917.6,6541.1 L5920.1,6531.8 L5929.5,6523.1 L5926.2,6513.9 L5937.8,6492.8 L5961.2,6493.6 L5969.1,6502.2 L5992.1,6476.7 L6000.7,6471.8 L6012.7,6471.7 L6029.9,6464.3 Z","cx":6002.2,"cy":6580.3},{"n":"강서구","sl":"강서","d":"M5476.8,6967.1 L5482.5,6955.3 L5504.2,6955.7 L5517.4,6945.8 L5520.4,6938.0 L5520.0,6928.4 L5509.5,6921.3 L5506.4,6914.3 L5510.5,6904.4 L5500.6,6888.1 L5489.8,6892.3 L5483.6,6885.5 L5466.4,6881.7 L5451.4,6866.2 L5449.6,6858.0 L5440.7,6859.4 L5440.0,6848.2 L5428.9,6833.1 L5424.3,6822.8 L5426.0,6819.5 L5437.7,6820.6 L5448.0,6814.9 L5453.5,6818.5 L5467.6,6815.6 L5481.2,6825.2 L5490.0,6826.6 L5506.5,6818.1 L5520.0,6820.8 L5526.5,6804.7 L5552.6,6796.4 L5567.4,6797.5 L5575.4,6803.9 L5576.6,6809.7 L5570.9,6819.2 L5566.0,6816.6 L5563.2,6820.4 L5575.7,6838.9 L5582.8,6837.2 L5584.8,6836.0 L5581.6,6831.4 L5581.1,6819.4 L5593.5,6817.3 L5594.6,6812.8 L5586.1,6804.0 L5583.7,6790.8 L5577.1,6786.5 L5579.3,6782.1 L5594.2,6787.6 L5592.0,6770.7 L5595.2,6762.7 L5584.3,6748.6 L5584.5,6737.7 L5573.2,6716.3 L5590.0,6696.0 L5595.1,6695.1 L5604.4,6685.3 L5624.6,6688.3 L5647.0,6679.8 L5640.5,6671.8 L5648.8,6664.9 L5648.6,6670.7 L5650.7,6665.0 L5655.0,6666.0 L5663.1,6679.3 L5669.8,6680.6 L5687.5,6671.9 L5709.7,6654.0 L5716.2,6652.0 L5725.0,6659.4 L5773.6,6654.3 L5804.9,6644.0 L5818.6,6633.4 L5821.5,6641.0 L5813.0,6700.5 L5789.7,6728.0 L5759.5,6749.0 L5754.3,6757.2 L5752.9,6805.5 L5748.5,6830.8 L5746.6,6872.1 L5733.8,6884.9 L5723.5,6905.5 L5712.4,6914.2 L5698.5,6931.4 L5699.2,6936.1 L5694.3,6935.6 L5694.3,6943.9 L5689.8,6955.0 L5689.4,6977.5 L5678.6,6978.3 L5656.4,6989.7 L5654.8,7008.8 L5652.5,7010.6 L5621.5,7010.6 L5621.6,6992.6 L5626.5,6977.1 L5629.5,6977.8 L5632.0,6932.7 L5641.7,6916.7 L5626.2,6911.3 L5610.3,6941.2 L5607.0,6985.2 L5598.4,7002.3 L5600.0,7009.6 L5571.0,7004.7 L5573.9,6998.3 L5577.2,7001.1 L5574.0,6987.2 L5574.1,6995.7 L5569.1,7000.3 L5514.4,7000.4 L5512.1,7003.1 L5504.9,6987.8 L5498.9,6987.9 L5479.0,6965.5 L5476.8,6967.1 Z","cx":5665.6,"cy":6821.8},{"n":"연제구","sl":"연제","d":"M6000.8,6736.6 L6035.4,6743.3 L6042.4,6747.0 L6048.6,6759.5 L6041.2,6777.9 L6026.0,6765.9 L6013.4,6771.4 L6013.5,6788.1 L6002.7,6802.8 L6010.2,6812.8 L6005.3,6816.0 L5997.9,6814.3 L5985.8,6820.4 L5976.6,6805.5 L5982.6,6797.8 L5984.1,6788.4 L5977.5,6779.0 L5964.7,6769.0 L5961.3,6778.1 L5946.5,6774.3 L5944.4,6759.6 L5924.5,6756.3 L5916.8,6738.8 L5918.6,6733.2 L5927.3,6738.6 L5946.0,6739.9 L5949.9,6735.1 L5964.5,6731.4 L5969.0,6724.6 L5976.7,6721.3 L5981.3,6721.6 L5986.7,6730.4 L6000.8,6736.6 Z","cx":5991.2,"cy":6770.2},{"n":"수영구","sl":"수영","d":"M6048.4,6753.0 L6069.6,6803.2 L6074.7,6806.4 L6087.7,6826.2 L6066.3,6832.7 L6065.2,6829.4 L6060.7,6829.4 L6054.3,6834.4 L6048.4,6846.3 L6053.9,6851.6 L6053.6,6862.9 L6040.9,6874.2 L6023.3,6857.5 L6025.7,6852.5 L6021.5,6835.6 L6002.7,6802.8 L6013.5,6788.1 L6013.4,6771.4 L6026.0,6765.9 L6041.2,6777.9 L6048.6,6759.5 L6048.4,6753.0 Z","cx":6045.8,"cy":6816.3},{"n":"사상구","sl":"사상","d":"M5801.4,6729.8 L5807.3,6734.8 L5812.9,6731.2 L5825.5,6739.5 L5826.8,6744.0 L5865.8,6750.1 L5862.3,6766.9 L5845.5,6783.4 L5850.0,6800.3 L5845.5,6819.0 L5856.6,6828.9 L5856.6,6846.5 L5852.4,6850.2 L5856.5,6856.0 L5848.6,6870.1 L5828.2,6862.3 L5817.2,6863.0 L5833.3,6872.6 L5830.2,6879.0 L5831.8,6896.5 L5824.4,6904.2 L5799.6,6901.9 L5787.0,6918.2 L5780.3,6919.4 L5754.4,6907.4 L5746.2,6917.5 L5742.3,6901.7 L5751.6,6874.5 L5751.6,6871.6 L5746.6,6872.1 L5748.5,6830.8 L5752.9,6805.5 L5753.6,6759.3 L5759.5,6749.0 L5780.4,6736.0 L5801.1,6716.5 L5803.8,6719.7 L5801.4,6729.8 Z","cx":5799.4,"cy":6812.2}],"daegu":[{"n":"중구","sl":"중","d":"M5005.0,5089.0 L5056.8,5102.9 L5068.9,5100.1 L5072.7,5102.6 L5076.7,5116.5 L5073.3,5126.2 L5065.1,5134.1 L5064.4,5148.2 L5015.0,5144.8 L4998.7,5135.8 L4997.3,5123.1 L5008.7,5111.2 L5008.3,5105.3 L5003.1,5107.5 L5000.9,5104.6 L5002.8,5097.4 L5006.4,5097.8 L5005.0,5089.0 Z","cx":5038.0,"cy":5119.8},{"n":"동구","sl":"동","d":"M5234.7,4762.6 L5236.2,4768.4 L5245.1,4774.0 L5277.1,4780.5 L5294.6,4792.3 L5310.1,4816.9 L5303.8,4825.5 L5302.6,4835.1 L5313.7,4845.2 L5317.8,4855.7 L5332.2,4865.1 L5325.9,4896.1 L5316.1,4905.7 L5321.4,4912.1 L5328.0,4934.5 L5319.6,4950.1 L5321.7,4951.5 L5316.6,4960.6 L5316.9,4966.8 L5313.7,4969.0 L5325.6,4991.3 L5349.8,5004.0 L5357.3,5020.1 L5358.5,5023.6 L5352.2,5031.4 L5354.1,5049.0 L5361.5,5069.9 L5360.2,5081.9 L5354.4,5092.6 L5360.3,5102.7 L5356.7,5110.5 L5358.5,5121.4 L5349.4,5127.4 L5341.0,5142.0 L5330.8,5145.9 L5317.3,5156.9 L5307.4,5154.4 L5289.2,5136.1 L5264.6,5134.0 L5249.7,5141.8 L5214.0,5138.0 L5203.6,5130.9 L5203.4,5119.9 L5195.5,5104.2 L5174.4,5105.2 L5166.4,5100.8 L5163.6,5095.7 L5156.3,5097.4 L5147.8,5092.0 L5135.6,5096.1 L5116.5,5107.2 L5106.1,5119.9 L5076.7,5116.5 L5072.7,5102.6 L5061.5,5095.3 L5071.1,5085.4 L5081.2,5066.8 L5091.3,5058.2 L5102.5,5065.3 L5109.7,5056.5 L5100.6,5029.9 L5103.1,5022.2 L5110.5,5021.1 L5111.6,4999.8 L5110.0,4976.6 L5104.9,4968.9 L5101.7,4968.9 L5103.1,4963.4 L5097.3,4954.4 L5099.9,4931.1 L5093.5,4929.2 L5093.8,4914.5 L5100.1,4900.5 L5092.0,4890.8 L5092.8,4881.7 L5083.8,4870.6 L5086.9,4862.3 L5085.0,4856.4 L5066.6,4835.2 L5054.8,4829.2 L5078.8,4797.7 L5084.5,4784.6 L5090.8,4785.5 L5098.9,4781.2 L5107.6,4782.9 L5127.3,4774.7 L5135.1,4774.9 L5147.3,4782.5 L5158.1,4776.3 L5175.3,4774.8 L5183.3,4768.2 L5234.7,4762.6 Z","cx":5208.8,"cy":4957.5},{"n":"서구","sl":"서","d":"M4960.2,5061.6 L5001.5,5069.8 L5013.0,5075.7 L5009.4,5090.1 L5005.0,5089.0 L5006.4,5097.8 L5003.0,5097.2 L5000.7,5102.7 L5003.1,5107.5 L5008.3,5105.3 L5008.7,5111.2 L4997.3,5123.1 L4998.1,5129.8 L4947.5,5149.7 L4935.0,5144.7 L4931.7,5139.1 L4918.7,5139.0 L4919.7,5132.7 L4907.7,5132.1 L4905.5,5128.3 L4907.3,5124.3 L4891.2,5113.4 L4895.2,5105.6 L4892.4,5092.9 L4885.8,5080.6 L4888.4,5076.8 L4902.3,5072.6 L4905.3,5068.0 L4909.3,5072.9 L4921.5,5074.0 L4933.5,5055.6 L4954.9,5046.7 L4957.5,5051.0 L4954.7,5054.4 L4960.2,5061.6 Z","cx":4947.9,"cy":5100.3},{"n":"남구","sl":"남","d":"M4998.7,5135.8 L5015.0,5144.8 L5037.9,5144.2 L5065.1,5149.8 L5059.5,5196.3 L5063.1,5215.0 L5057.9,5215.7 L5047.9,5244.5 L5037.2,5248.6 L5031.7,5257.8 L5024.6,5261.6 L5016.9,5262.3 L5012.6,5251.1 L5008.2,5251.1 L4991.5,5233.4 L4991.9,5227.1 L4987.3,5220.2 L4984.8,5223.6 L4976.7,5221.6 L4966.9,5201.0 L4961.9,5197.4 L4974.7,5175.5 L4997.0,5157.1 L4998.7,5135.8 Z","cx":5012.3,"cy":5199.2},{"n":"북구","sl":"북","d":"M5067.4,4836.0 L5086.9,4862.3 L5083.8,4870.6 L5092.8,4881.7 L5092.0,4890.8 L5100.1,4900.5 L5093.8,4914.5 L5093.5,4929.2 L5099.9,4931.1 L5097.3,4954.4 L5103.1,4963.4 L5101.7,4968.9 L5104.9,4968.9 L5110.0,4976.6 L5110.5,5021.1 L5103.1,5022.2 L5100.6,5029.9 L5104.3,5045.6 L5109.9,5054.3 L5102.5,5065.3 L5091.3,5058.2 L5081.2,5066.8 L5071.1,5085.4 L5061.9,5093.8 L5068.9,5100.1 L5056.8,5102.9 L5009.4,5090.1 L5013.0,5075.7 L5001.5,5069.8 L4960.8,5062.0 L4954.7,5054.4 L4957.5,5051.0 L4954.9,5046.7 L4933.5,5055.6 L4924.3,5072.5 L4920.0,5074.4 L4909.3,5072.9 L4895.0,5062.1 L4879.9,5056.2 L4869.1,5056.2 L4863.5,5060.5 L4865.0,5034.9 L4869.0,5023.3 L4873.8,5016.2 L4886.9,5011.6 L4897.5,5000.2 L4903.8,4987.2 L4911.3,4983.3 L4912.9,4972.3 L4920.8,4955.2 L4921.6,4939.6 L4917.3,4918.7 L4921.7,4899.9 L4919.1,4893.9 L4913.3,4891.2 L4905.8,4858.9 L4910.0,4847.1 L4914.8,4846.7 L4938.5,4860.5 L4944.7,4882.4 L4957.7,4894.1 L4964.9,4866.6 L4979.7,4865.0 L4981.6,4860.2 L4995.5,4852.0 L5015.7,4854.5 L5029.2,4849.8 L5034.8,4846.0 L5034.5,4839.9 L5053.8,4833.8 L5054.8,4829.2 L5067.4,4836.0 Z","cx":5009.1,"cy":4966.2},{"n":"수성구","sl":"수성","d":"M5154.5,5096.8 L5163.6,5095.7 L5169.2,5102.9 L5179.1,5106.2 L5195.5,5104.2 L5203.4,5119.9 L5203.6,5130.9 L5215.3,5138.5 L5249.7,5141.8 L5264.6,5134.0 L5289.2,5136.1 L5292.7,5140.9 L5284.9,5143.3 L5291.8,5151.0 L5294.6,5166.7 L5293.5,5178.0 L5289.2,5185.3 L5291.0,5193.6 L5284.8,5196.8 L5279.7,5193.9 L5259.2,5216.2 L5260.0,5228.2 L5269.4,5238.0 L5276.4,5263.6 L5262.2,5269.8 L5242.1,5291.9 L5235.7,5293.0 L5229.4,5287.7 L5222.6,5297.4 L5208.5,5303.7 L5193.7,5291.6 L5152.1,5281.8 L5147.9,5273.2 L5131.2,5274.9 L5115.3,5271.1 L5104.8,5273.9 L5093.1,5265.9 L5080.1,5271.4 L5052.9,5264.9 L5043.5,5265.6 L5031.7,5257.8 L5037.2,5248.6 L5049.6,5242.3 L5057.9,5215.7 L5063.1,5215.0 L5059.5,5196.3 L5064.0,5172.6 L5064.1,5137.3 L5073.3,5126.2 L5076.7,5116.5 L5106.1,5119.9 L5116.5,5107.2 L5135.6,5096.1 L5147.8,5092.0 L5154.5,5096.8 Z","cx":5165.1,"cy":5205.9},{"n":"달서구","sl":"달서","d":"M4820.5,5242.8 L4821.0,5224.8 L4817.4,5207.7 L4800.8,5199.3 L4793.3,5187.7 L4801.8,5140.3 L4818.7,5116.1 L4828.4,5116.6 L4841.3,5124.9 L4855.2,5127.7 L4869.2,5121.7 L4872.4,5113.0 L4884.8,5117.4 L4891.2,5113.4 L4907.3,5124.3 L4905.5,5128.3 L4907.7,5132.1 L4919.7,5132.7 L4918.7,5139.0 L4931.7,5139.1 L4935.0,5144.7 L4947.5,5149.7 L4998.1,5129.8 L4997.0,5157.1 L4974.7,5175.5 L4961.9,5197.4 L4966.9,5201.0 L4976.7,5221.6 L4984.8,5223.6 L4987.3,5220.2 L4991.9,5227.1 L4991.5,5233.4 L5008.2,5251.1 L5012.6,5251.1 L5016.9,5262.3 L5024.6,5261.6 L5019.6,5282.5 L5002.5,5289.8 L4988.8,5286.3 L4984.1,5292.0 L4990.5,5328.2 L4980.7,5341.0 L4959.9,5344.9 L4955.2,5329.7 L4949.1,5327.2 L4943.4,5315.4 L4934.6,5308.4 L4934.5,5304.4 L4926.1,5311.8 L4910.0,5308.5 L4907.2,5297.0 L4898.4,5294.7 L4887.9,5283.8 L4882.3,5266.1 L4869.4,5265.1 L4870.6,5261.4 L4880.1,5256.3 L4878.6,5253.3 L4855.4,5237.4 L4834.8,5231.9 L4820.5,5242.8 Z","cx":4906.3,"cy":5229.5}]}""")

# _local 미수집 시 폴백 샘플(화면이 비지 않게 · 상승장 가정)
_LOCAL_SAMPLE = json.loads(r"""{"incheon":{"name":"인천","gu":{"중구":{"mm":0.08,"js":-0.0,"jr":61.5},"동구":{"mm":-0.02,"js":0.11,"jr":57.8},"미추홀구":{"mm":-0.03,"js":0.1,"jr":53.5},"연수구":{"mm":0.12,"js":-0.03,"jr":54.2},"남동구":{"mm":0.12,"js":0.2,"jr":54.6},"부평구":{"mm":0.04,"js":0.14,"jr":65.3},"계양구":{"mm":0.18,"js":0.07,"jr":65.7},"서구":{"mm":-0.03,"js":0.21,"jr":56.8}},"others":{"mm":0.08,"js":0.04,"jr":61,"sale":[97.0,97.2,97.4,97.6,97.8,98.0,98.2,98.4,98.7,98.9,99.1,99.3,99.5,99.7,99.9,100.1,100.3,100.5,100.7,100.9,101.1,101.3,101.6,101.8,102.0,102.2,102.4,102.6,102.8,103.0],"jeonse":[96.0,96.1,96.3,96.4,96.6,96.7,96.8,97.0,97.1,97.2,97.4,97.5,97.7,97.8,97.9,98.1,98.2,98.3,98.5,98.6,98.8,98.9,99.0,99.2,99.3,99.4,99.6,99.7,99.9,100.0]}},"busan":{"name":"부산","gu":{"중구":{"mm":0.01,"js":-0.01,"jr":57.0},"서구":{"mm":0.28,"js":0.0,"jr":60.6},"동구":{"mm":0.21,"js":0.06,"jr":60.1},"영도구":{"mm":-0.02,"js":-0.03,"jr":55.7},"부산진구":{"mm":0.22,"js":0.08,"jr":57.1},"동래구":{"mm":0.18,"js":0.09,"jr":56.9},"남구":{"mm":0.27,"js":0.16,"jr":56.2},"북구":{"mm":0.18,"js":0.11,"jr":64.4},"해운대구":{"mm":0.24,"js":0.04,"jr":65.7},"사하구":{"mm":-0.0,"js":0.08,"jr":62.8},"금정구":{"mm":0.01,"js":0.1,"jr":53.5},"강서구":{"mm":0.22,"js":0.18,"jr":60.4},"연제구":{"mm":0.3,"js":0.04,"jr":62.0},"수영구":{"mm":0.19,"js":0.12,"jr":58.9},"사상구":{"mm":0.29,"js":0.23,"jr":59.2}},"others":{"mm":0.08,"js":0.04,"jr":61,"sale":[97.0,97.2,97.4,97.6,97.8,98.0,98.2,98.4,98.7,98.9,99.1,99.3,99.5,99.7,99.9,100.1,100.3,100.5,100.7,100.9,101.1,101.3,101.6,101.8,102.0,102.2,102.4,102.6,102.8,103.0],"jeonse":[96.0,96.1,96.3,96.4,96.6,96.7,96.8,97.0,97.1,97.2,97.4,97.5,97.7,97.8,97.9,98.1,98.2,98.3,98.5,98.6,98.8,98.9,99.0,99.2,99.3,99.4,99.6,99.7,99.9,100.0]}},"daegu":{"name":"대구","gu":{"중구":{"mm":0.22,"js":-0.03,"jr":62.1},"동구":{"mm":0.21,"js":0.25,"jr":63.7},"서구":{"mm":0.06,"js":0.07,"jr":61.7},"남구":{"mm":-0.04,"js":0.09,"jr":55.2},"북구":{"mm":-0.0,"js":-0.03,"jr":63.0},"수성구":{"mm":0.0,"js":0.02,"jr":58.1},"달서구":{"mm":0.3,"js":-0.03,"jr":58.8}},"others":{"mm":0.08,"js":0.04,"jr":61,"sale":[97.0,97.2,97.4,97.6,97.8,98.0,98.2,98.4,98.7,98.9,99.1,99.3,99.5,99.7,99.9,100.1,100.3,100.5,100.7,100.9,101.1,101.3,101.6,101.8,102.0,102.2,102.4,102.6,102.8,103.0],"jeonse":[96.0,96.1,96.3,96.4,96.6,96.7,96.8,97.0,97.1,97.2,97.4,97.5,97.7,97.8,97.9,98.1,98.2,98.3,98.5,98.6,98.8,98.9,99.0,99.2,99.3,99.4,99.6,99.7,99.9,100.0]}}}""")


_MAPC_HTML = r'''<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{--bg:#FCFCFA;--card:#fff;--ink:#34352f;--muted:#9a9b92;--line:#ECEDE7;--line2:#DEDED7;
 --sage:#A7BBA9;--sage2:#7E9A83;--up:#B65F5A;--dn:#5A7CA0;--jr:#6E8FA8;
 --kfont:'Pretendard',-apple-system,BlinkMacSystemFont,sans-serif;}
*{box-sizing:border-box}
body{margin:0;background:transparent;color:var(--ink);font-family:var(--kfont);font-size:14px;-webkit-font-smoothing:antialiased;}
.up{color:var(--up)}.dn{color:var(--dn)}
.hd{display:flex;justify-content:space-between;align-items:flex-end;gap:10px;margin:0 0 10px;flex-wrap:wrap}
.h1{font-size:18px;font-weight:800;letter-spacing:-.02em}
.crumb{font-size:11.5px;color:var(--muted);margin-top:3px;display:flex;align-items:center;gap:6px}
.crumb b{color:var(--ink)} .crumb .back{cursor:pointer;border:1px solid var(--line2);border-radius:7px;padding:1px 8px;color:var(--ink);background:var(--card);font-size:11px}
.live{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:var(--sage2);font-weight:700;margin-left:6px}
.live i{width:7px;height:7px;border-radius:50%;background:var(--sage2);animation:bl 1.6s ease-in-out infinite}
@keyframes bl{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.35;transform:scale(.7)}}
.seg{display:inline-flex;border:1px solid var(--line2);border-radius:8px;overflow:hidden;background:var(--card)}
.seg button{border:none;background:none;padding:5px 12px;font-size:11.5px;color:var(--muted);cursor:pointer;border-right:1px solid var(--line);font-family:var(--kfont)}
.seg button:last-child{border-right:none}.seg button.on{background:#EEF1EC;color:var(--ink);font-weight:700}
.chips{display:flex;flex-wrap:wrap;gap:7px;margin:0 0 12px}
.chip{font-size:12.5px;color:var(--ink);background:var(--card);border:1px solid var(--line2);border-radius:999px;padding:6px 15px;cursor:pointer;transition:all .15s ease}
.chip:hover{border-color:var(--sage)} .chip.on{background:var(--sage2);color:#fff;border-color:var(--sage2);box-shadow:0 3px 10px rgba(126,154,131,.3)}
.maparea{position:relative;width:100%;height:500px;border:1px solid var(--line);border-radius:16px;background:var(--bg);overflow:hidden;margin-bottom:13px}
#big{display:block;width:100%;height:100%;cursor:crosshair}
.dist{stroke:#fff;stroke-width:.7;transition:fill .4s ease,opacity .3s}
.dlabel{pointer-events:none;fill:#2f302a;font-family:var(--kfont);font-weight:600}
#hoverLabel{pointer-events:none;font-family:var(--kfont);font-weight:800;fill:#23241d;opacity:0;transition:opacity .1s}
.nav{position:absolute;top:11px;right:11px;width:140px;background:rgba(252,252,250,.92);border:1px solid var(--line2);border-radius:12px;padding:8px 8px 6px;backdrop-filter:blur(5px);box-shadow:0 6px 20px rgba(52,53,47,.10)}
.nav .nt{font-size:9.5px;font-weight:800;color:var(--muted);letter-spacing:.04em;margin:0 2px 3px;display:flex;justify-content:space-between}
.nav svg{display:block;width:100%;height:auto}
#kland{fill:#EDEFE9;stroke:#D7DBD0;stroke-width:1.2}
.kdot{cursor:pointer}.kdot circle{transition:r .15s ease,fill .2s ease}
.kdot text{font-size:7.2px;font-weight:800;fill:#5d6258;font-family:var(--kfont);pointer-events:none}
.kdot.on .pulse{animation:pl 1.7s ease-out infinite}
@keyframes pl{0%{r:4;opacity:.5}100%{r:13;opacity:0}}
.legend{position:absolute;left:13px;top:11px;display:flex;flex-direction:column;align-items:flex-start;gap:2px;width:190px;font-size:10px;color:var(--muted);background:rgba(252,252,250,.94);border:1px solid var(--line2);border-radius:9px;padding:6px 9px 5px;backdrop-filter:blur(4px)}
.legend .lgcap{font-size:9.5px;font-weight:700;color:#5d6258}
.legend .lgrow{display:flex;width:100%}
.legend .lgsw{flex:1;height:11px}
.legend .lgsw.neu{outline:1.4px solid #C9CABF;outline-offset:-1.4px}
.legend .lgticks{position:relative;width:100%;height:11px;margin-top:1px}
.legend .lgticks span{position:absolute;font-size:8.5px;font-weight:700;color:#6f7066;white-space:nowrap}
.pills{position:absolute;right:11px;bottom:12px;display:inline-flex;gap:4px;background:rgba(252,252,250,.92);border:1px solid var(--line2);border-radius:9px;padding:3px;backdrop-filter:blur(4px)}
.pills button{border:none;border-radius:7px;padding:4px 10px;font-size:10.5px;color:var(--muted);cursor:pointer;background:transparent;font-family:var(--kfont)}
.pills button.on{background:#EEF1EC;color:var(--ink);font-weight:700}
.tip{position:absolute;pointer-events:none;background:var(--card);border:1px solid var(--line2);border-radius:9px;padding:8px 11px;font-size:12px;min-width:148px;box-shadow:0 6px 22px rgba(52,53,47,.14);opacity:0;transform:translateY(4px);transition:opacity .14s,transform .14s;z-index:7}
.tip .up{color:var(--up)}.tip .dn{color:var(--dn)}
.phbadge{position:absolute;left:50%;top:11px;transform:translateX(-50%);font-size:10px;font-weight:700;color:#9A7B43;background:rgba(255,250,238,.94);border:1px solid #E6D9B8;border-radius:999px;padding:3px 11px;backdrop-filter:blur(4px);box-shadow:0 2px 8px rgba(52,53,47,.08);z-index:6}
.vctx{font-weight:700}.vctx.hi{color:#7E9A83}.vctx.lo{color:#5A7CA0}.vctx.nm{color:#9a9b92}
.cnt{color:#5b5c54}
.mrow{display:flex;gap:14px;align-items:flex-start;margin-bottom:6px}
.mleft{flex:2;min-width:0} .mright{flex:3;min-width:0}
table.mx{width:100%;border-collapse:collapse;table-layout:fixed}
.mxwrap{border:1px solid var(--line);border-radius:12px;overflow-y:auto;max-height:440px;}
.mxwrap::-webkit-scrollbar{width:8px}.mxwrap::-webkit-scrollbar-thumb{background:#E2E3DC;border-radius:6px}
table.mx thead th{position:sticky;top:0;z-index:2}
table.mx th{font-size:10.5px;color:var(--muted);font-weight:600;text-align:right;padding:7px 8px;background:var(--card)}
table.mx th i{font-style:normal;font-weight:600;font-size:8.5px;color:#B5B7AD;margin-left:2px;vertical-align:1px}
table.mx th:first-child{text-align:left}
table.mx td{padding:7px 8px;border-top:1px solid var(--line);text-align:right;vertical-align:middle;font-size:11.5px}
table.mx td:first-child{text-align:left;font-weight:700;font-size:12px}
table.mx tr:hover{background:#FAFAF6}
.dl{font-weight:800}.muted{color:var(--muted)}
.panel{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:12px 14px;}
.p-h{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
.p-t{font-size:12.5px;font-weight:800}
.p-lg{font-size:10.5px;color:var(--muted);display:flex;gap:12px}.p-lg i{font-style:normal}
.p-r{display:flex;align-items:center;gap:9px}
.cmptog,.cmpmet{display:flex;flex:none}
.cmptog button,.cmpmet button{border:1px solid var(--line2);background:var(--card);color:var(--muted);font-family:var(--kfont);cursor:pointer}
.cmptog button{font-size:9.5px;padding:2px 7px}.cmpmet button{font-size:10px;padding:2px 9px}
.cmptog button:first-child,.cmpmet button:first-child{border-radius:6px 0 0 6px}
.cmptog button:last-child,.cmpmet button:last-child{border-radius:0 6px 6px 0;border-left:none}
.cmptog button.on,.cmpmet button.on{background:#EEF1EC;color:var(--ink);font-weight:700}
.cmpctl{display:flex;flex-wrap:wrap;align-items:center;gap:7px;margin:0 0 7px}
.cmpchips{display:flex;flex-wrap:wrap;gap:5px}
.cmpchip{display:inline-flex;align-items:center;gap:4px;font-size:11px;color:#5b5c54;background:var(--card);border:1px solid var(--line2);border-radius:999px;padding:3px 9px;cursor:pointer;transition:all .12s}
.cmpchip .cd{width:8px;height:8px;border-radius:50%;background:#C4C6BD}
.cmpchip.on{color:var(--ink);font-weight:700}
.dot{display:inline-block;width:9px;height:9px;border-radius:2px;vertical-align:-1px;margin-right:3px}
#trChart{display:block;width:100%;height:auto}
.axt{fill:var(--muted);font-size:10px;font-family:var(--kfont)}
.axtitle{fill:#8b8c84;font-size:8px;font-family:var(--kfont)}
.vtip{position:absolute;pointer-events:none;background:var(--card);border:1px solid var(--line2);border-radius:7px;padding:6px 9px;font-size:11px;opacity:0;transition:opacity .12s;white-space:nowrap;box-shadow:0 4px 14px rgba(52,53,47,.12);z-index:6}
.note{color:var(--muted);font-size:10.8px;margin-top:9px;line-height:1.6}
.draw{stroke-dasharray:var(--L);stroke-dashoffset:var(--L);}
.drawn{stroke-dashoffset:0;transition:stroke-dashoffset .85s ease}
@media(max-width:760px){.maparea{height:400px}.nav{display:none}.mrow{flex-direction:column}.mleft,.mright{width:100%;flex:none}.mxwrap{max-height:280px}}
</style></head><body>
<div class="hd">
  <div><div class="crumb"><span class="back" id="back">‹ 전국</span> <span>전국</span> › <b id="crName">서울</b>
      <span class="live"><i></i> 방금 갱신</span></div></div>
  <div class="seg" id="periodSeg"><button data-p="1y">1년</button><button data-p="3y">3년</button><button data-p="all" class="on">전체</button></div>
</div>
<div class="chips" id="chips"></div>
<div class="maparea" id="maparea">
  <div class="legend" id="legend"></div>
  <svg id="big" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet" role="img" aria-label="상세 지도"></svg>
  <div class="pills" id="metricPills"><button data-m="mm" class="on">매매</button><button data-m="js">전세</button><button data-m="v">거래</button><button data-m="jr">전세가율</button></div>
  <div class="nav"><div class="nt"><span>전국</span><span style="color:#C4C6BD">탭하여 이동</span></div>
    <svg viewBox="0 0 120 150" role="img" aria-label="한반도 내비게이터">
      <path id="kland" d="M44 14 C58 8 74 12 80 24 C86 34 82 44 88 52 C95 61 96 72 90 80 C97 86 100 96 95 106 C101 112 100 124 92 130 C86 134 80 128 76 120 C70 126 62 122 60 114 C52 118 44 114 42 106 C33 108 24 102 24 92 C16 90 12 80 18 72 C12 64 14 52 24 48 C22 38 28 26 38 22 C39 18 41 15 44 14 Z"></path>
      <g id="kdots"></g></svg></div>
  <div class="tip" id="tip"></div>
  <div class="phbadge" id="phbadge" hidden>예시 배치 · 실제 구 경계 아님</div>
</div>
<div class="mrow">
  <div class="mleft"><div class="mxwrap"><table class="mx"><thead><tr><th style="width:34%">지역</th><th>매매Δ<i>월</i></th><th>전세Δ<i>월</i></th><th>거래<i>주</i></th><th>전세가율<i>월</i></th></tr></thead><tbody id="mxBody"></tbody></table></div></div>
  <div class="mright"><div class="panel"><div class="p-h"><span class="p-t" id="trTitle"></span>
    <span class="p-r"><span class="p-lg" id="trLeg"><i><span class="dot" style="background:#B65F5A"></span>매매</i><i><span class="dot" style="background:#5A7CA0"></span>전세</i></span>
      <span class="cmptog" id="cmpTog"><button data-cm="single" class="on">단일</button><button data-cm="cmp">비교</button></span></span></div>
    <div class="cmpctl" id="cmpCtl" hidden><span class="cmpmet" id="cmpMet"><button data-m="mm" class="on">매매</button><button data-m="js">전세</button></span><span class="cmpchips" id="cmpChips"></span></div>
    <div style="position:relative"><svg id="trChart" viewBox="0 0 620 230" role="img" aria-label="가격지수 추이"></svg><div class="vtip" id="vtip"></div></div></div></div>
</div>
<div class="note" id="note"></div>
<script>
const D=__D__,LGEO=__LGEO__,LOCAL=__LOCAL__,TREND=__TREND__,GN3=__GN3__,ASOF=__ASOF__;
const ORDER=["gn3","seoul","gg","incheon","daegu","busan"];
const RNAME={gn3:"강남3구",seoul:"서울",gg:"경기",incheon:"인천",daegu:"대구",busan:"부산"};
const SUDO=new Set(["gn3","seoul","gg"]);
const NAVPOS={incheon:[34,54],seoul:[50,47],gn3:[54,55,1],gg:[64,45],daegu:[82,96],busan:[95,118]};
let region="seoul",metric="mm",period="all",busy=false;
const fmtP=v=>(v>0?"+":"")+(+v||0).toFixed(2)+"%";
const cls=v=>v>0.005?"up":(v<-0.005?"dn":"");
function colMM(v){if(v>=.30)return"#C16C64";if(v>=.15)return"#D89089";if(v>=.05)return"#E9BDB8";if(v>-.02)return"#EFEEE9";if(v>-.10)return"#C9D6E5";return"#A9C0DA";}
function colJR(v){if(v>=68)return"#6E8FA8";if(v>=63)return"#92ABC1";if(v>=58)return"#B4C7D8";if(v>=53)return"#D2DEE9";return"#EBF0F5";}
function vrat(d){return (d.vavg!=null&&d.vavg>0&&d.v!=null)?(d.v/d.vavg-1)*100:null;}
function colVR(p){if(p>=100)return"#5E8770";if(p>=50)return"#8FB39B";if(p>=15)return"#BBD2C0";if(p>-15)return"#EFEEE9";if(p>-40)return"#DDE4D8";return"#C9D2C4";}
function volCtx(d){const p=vrat(d);if(p==null)return null;const m=d.v/d.vavg;
  if(Math.abs(p)<15)return{full:"평소 수준",bare:"평소",cls:"nm"};
  if(m>=2)return{full:"평소 "+m.toFixed(1)+"×",bare:m.toFixed(1)+"×",cls:"hi"};
  if(p>0)return{full:"평소 +"+Math.round(p)+"%",bare:"+"+Math.round(p)+"%",cls:"hi"};
  return{full:"평소 "+Math.round(p)+"%",bare:Math.round(p)+"%",cls:"lo"};}
function fillOf(d){if(metric==="v"){const p=vrat(d);return p==null?"#F1F2EC":colVR(p);}if(metric==="jr")return colJR(d.jr==null?0:d.jr);return colMM(metric==="js"?d.js:d.mm);}
function pathsOf(r){
  if(SUDO.has(r)){
    let f=r==="gn3"?D.filter(d=>GN3.includes(d.n)):r==="seoul"?D.filter(d=>d.sd==="seoul"):D.filter(d=>d.sd==="gg");
    return f.map(d=>({n:d.n,sl:d.sl,d:d.d,cx:d.cx,cy:d.cy,mm:d.mm,js:d.js,v:d.v,vc:d.vc,vavg:d.vavg,jr:d.jr}));}
  const geo=LGEO[r]||[],lc=(LOCAL[r]||{}).gu||{};
  return geo.map(t=>{const m=lc[t.n]||{};
    return {n:t.n,sl:t.sl,d:t.d,cx:t.cx,cy:t.cy,mm:m.mm||0,js:m.js||0,v:null,jr:(m.jr==null?null:m.jr)};});
}
function pathNums(d){return (d.match(/-?\d+\.?\d*/g)||[]).map(Number);}
function vbOf(paths){let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
  paths.forEach(d=>{const n=pathNums(d.d);for(let i=0;i+1<n.length;i+=2){const x=n[i],y=n[i+1];if(x<x0)x0=x;if(x>x1)x1=x;if(y<y0)y0=y;if(y>y1)y1=y;}});
  if(x1<x0)return[0,0,1100,1087];const px=(x1-x0)*0.07,py=(y1-y0)*0.15;
  return[x0-px,y0-py,(x1-x0)+2*px,(y1-y0)+2*py];}

function drawChips(){document.getElementById("chips").innerHTML=ORDER.map(r=>
  `<div class="chip ${r===region?"on":""}" data-r="${r}">${RNAME[r]}</div>`).join("");
  document.querySelectorAll(".chip").forEach(c=>c.onclick=()=>setRegion(c.dataset.r));}
function drawNav(){document.getElementById("kdots").innerHTML=ORDER.map(r=>{const p=NAVPOS[r];const on=r===region;const rad=p[2]?2.6:3.6;
  return `<g class="kdot ${on?"on":""}" data-r="${r}">${on?`<circle class="pulse" cx="${p[0]}" cy="${p[1]}" r="4" fill="#B65F5A"/>`:""}<circle class="main" cx="${p[0]}" cy="${p[1]}" r="${rad}" fill="${on?"#B65F5A":"#9aa39b"}"/><text x="${p[0]}" y="${p[1]-6}" text-anchor="middle">${p[2]?"강남3":RNAME[r]}</text></g>`;}).join("");
  document.querySelectorAll("#kdots .kdot").forEach(el=>el.onclick=()=>setRegion(el.dataset.r));}
function lgStepped(cells,ticks,cap){
  const sw=cells.map((c,i)=>{let r="";if(i===0)r=";border-radius:3px 0 0 3px";if(i===cells.length-1)r=";border-radius:0 3px 3px 0";
    return `<div class="lgsw${c.neu?" neu":""}" style="background:${c.c}${r}"></div>`;}).join("");
  const tk=ticks.map(t=>`<span style="${t.pos}">${t.t}</span>`).join("");
  return `<div class="lgcap">${cap}</div><div class="lgrow">${sw}</div><div class="lgticks">${tk}</div>`;}
function drawLegend(){let h="";
  if(metric==="v")h=lgStepped(
    [{c:"#C9D2C4"},{c:"#DDE4D8"},{c:"#EFEEE9",neu:true},{c:"#BBD2C0"},{c:"#8FB39B"},{c:"#5E8770"}],
    [{t:"한산",pos:"left:0"},{t:"평소",pos:"left:41.7%;transform:translateX(-50%);color:#34352f"},{t:"활발",pos:"right:0"}],
    "거래 평소 대비 · 주간");
  else if(metric==="jr")h=lgStepped(
    [{c:"#EBF0F5"},{c:"#D2DEE9"},{c:"#B4C7D8"},{c:"#92ABC1"},{c:"#6E8FA8"}],
    [{t:"53",pos:"left:20%;transform:translateX(-50%)"},{t:"58",pos:"left:40%;transform:translateX(-50%)"},{t:"63",pos:"left:60%;transform:translateX(-50%)"},{t:"68%",pos:"left:80%;transform:translateX(-50%)"}],
    "전세가율 % · 월간");
  else h=lgStepped(
    [{c:"#A9C0DA"},{c:"#C9D6E5"},{c:"#EFEEE9",neu:true},{c:"#E9BDB8"},{c:"#D89089"},{c:"#C16C64"}],
    [{t:"≤−.10",pos:"left:0"},{t:"0%",pos:"left:41.7%;transform:translateX(-50%);color:#34352f"},{t:"≥+.30",pos:"right:0"}],
    (metric==="mm"?"매매":"전세")+" 등락 % · 월간");
  document.getElementById("legend").innerHTML=h;}

let _paths=[],_vb=[0,0,100,100];
function pathsHTML(big){const ps=_paths.map((d,i)=>`<path class="dist" data-i="${i}" d="${d.d}" fill="${fillOf(d)}"></path>`).join("");
  const ref=Math.sqrt(_vb[2]*_vb[3]/Math.max(1,_paths.length));   // 평균 구역 한 변(viewBox 단위)
  const labs=_paths.map(d=>{const fs=ref*(d.sl.length>3?0.135:0.165);   // 화면 픽셀 균일 + 밀도(N) 보정
    return `<text class="dlabel" x="${d.cx}" y="${d.cy}" text-anchor="middle" dominant-baseline="middle" font-size="${fs.toFixed(1)}" paint-order="stroke" stroke="#FCFCFA" stroke-width="${(fs*0.22).toFixed(1)}" stroke-linejoin="round">${d.sl}</text>`;}).join("");
  return `<g id="paths">${ps}</g><g>${labs}</g>`;}
function drawMap(){_paths=pathsOf(region);_vb=vbOf(_paths);const svg=document.getElementById("big");
  svg.setAttribute("viewBox",_vb.join(" "));const big=_paths.length<=8;
  svg.innerHTML=pathsHTML(big)+`<text id="hoverLabel" text-anchor="middle" dominant-baseline="middle" paint-order="stroke" stroke="#FCFCFA" stroke-width="2.6" stroke-linejoin="round"></text>`;
  const tip=document.getElementById("tip"),area=document.getElementById("maparea"),pg=svg.querySelector("#paths"),hl=svg.querySelector("#hoverLabel");
  svg.querySelectorAll("path.dist").forEach(p=>{const d=_paths[+p.dataset.i];
    p.onmouseenter=()=>{p.style.stroke="#7E9A83";p.style.strokeWidth="1.6";pg.appendChild(p);
      const _vx=volCtx(d);const vline=d.v==null?'<div class="muted">거래 — 미수집(지방)</div>'
        :`<div class="muted">거래 ${d.v}건${_vx?` · <span class="vctx ${_vx.cls}">${_vx.full}</span>`:""}</div>`;
      tip.innerHTML=`<div style="font-weight:800;margin-bottom:4px">${d.n}</div><div class="muted">매매 <span class="${cls(d.mm)}">${fmtP(d.mm)}</span> · 전세 <span class="${cls(d.js)}">${fmtP(d.js)}</span></div>${vline}<div class="muted">전세가율 ${d.jr==null?"-":d.jr+"%"}</div><div class="muted" style="font-size:10px;margin-top:3px;color:#A9AB9F">매매·전세·전세가율 월간(전월대비) · 거래 주간</div>`;
      tip.style.opacity="1";tip.style.transform="translateY(0)";
      const _hf=Math.sqrt(_vb[2]*_vb[3]/Math.max(1,_paths.length))*0.20;
      hl.setAttribute("x",d.cx);hl.setAttribute("y",d.cy);hl.setAttribute("font-size",_hf.toFixed(1));hl.setAttribute("stroke-width",(_hf*0.22).toFixed(1));hl.textContent=d.sl;hl.style.opacity="1";};
    p.onmouseleave=()=>{p.style.stroke="#fff";p.style.strokeWidth=".7";tip.style.opacity="0";hl.style.opacity="0";};});
  area.onmousemove=e=>{const b=area.getBoundingClientRect();let x=e.clientX-b.left,y=e.clientY-b.top;
    let tx=x+14,ty=y+14;if(tx>b.width-176)tx-=190;if(ty>b.height-96)ty-=104;tip.style.left=tx+"px";tip.style.top=ty+"px";};
  area.onmouseleave=()=>{tip.style.opacity="0";hl.style.opacity="0";};}

function drawTable(){const rows=_paths.length?_paths:pathsOf(region);
  const sorted=[...rows].sort((a,b)=>(b.mm||-9)-(a.mm||-9));
  document.getElementById("mxBody").innerHTML=sorted.map(d=>{
    const _vx=volCtx(d);
    const vcell=d.v==null?'<span class="muted">–</span>'
      :`<span class="cnt">${d.v.toLocaleString()}</span>${_vx?` <span class="vctx ${_vx.cls}" style="font-size:10px">${_vx.bare}</span>`:""}`;
    return `<tr><td>${d.n}</td><td><span class="dl ${cls(d.mm)}">${fmtP(d.mm)}</span></td>`
      +`<td><span class="dl ${cls(d.js)}">${fmtP(d.js)}</span></td><td>${vcell}</td>`
      +`<td>${d.jr==null?"-":d.jr+"%"}</td></tr>`;}).join("");}

function trendOf(r){if(SUDO.has(r))return TREND[r]||{};const o=(LOCAL[r]||{}).others||{};return{sale:o.sale,jeonse:o.jeonse};}
function sliceP(a){const wk=SUDO.has(region);const n=period==="1y"?(wk?52:12):period==="3y"?(wk?156:36):1e9;return (a||[]).slice(-n);}
let _trH=230,_trB=188;   // 추이 차트 viewBox 높이(좌측 표 높이에 맞춰 동적 산정)
function fitTrendHeight(){
  try{
    const svg=document.getElementById("trChart");if(!svg){drawTrend();return;}
    const svgC=svg.parentElement;                 // position:relative 컨테이너
    const panel=svgC.closest(".panel");
    const left=document.querySelector(".mleft");
    const W=svgC.clientWidth||svg.clientWidth||500;
    if(left&&panel&&W>1){
      const headH=svgC.getBoundingClientRect().top-panel.getBoundingClientRect().top; // 패널 헤더+컨트롤 높이
      const targetH=Math.max(230,left.offsetHeight-headH-12);   // 좌측 표 높이 − 헤더 − 패딩
      _trH=Math.round(620*targetH/W);             // 렌더 높이 ≈ targetH 되도록 viewBox 높이 환산
    }else _trH=230;
    _trB=_trH-42;                                 // 플롯 바닥(축 라벨 42 확보)
    svg.setAttribute("viewBox","0 0 620 "+_trH);
  }catch(e){_trH=230;_trB=188;}
  drawTrend();
}
function drawChart(){const tk=trendOf(region);const sale=sliceP(tk.sale),jeon=sliceP(tk.jeonse);
  document.getElementById("trTitle").textContent=RNAME[region]+" 가격지수 추이";
  const svg=document.getElementById("trChart");const all=(sale||[]).concat(jeon||[]).filter(v=>v!=null);
  if(all.length<2){svg.innerHTML='<text class="axt" x="310" y="'+(_trH/2).toFixed(0)+'" text-anchor="middle">추이 데이터가 아직 없어요</text>';return;}
  const L=52,Rr=606,T0=14,B=_trB,W=Rr-L,Hh=B-T0,n=sale.length,wk=SUDO.has(region);
  let dmn=Math.min(...all),dmx=Math.max(...all);const pad=(dmx-dmn)*0.14||1,lo=dmn-pad,hi=dmx+pad,rr=(hi-lo)||1;
  const X=i=>L+(n<=1?0:i/(n-1)*W),Y=v=>B-(v-lo)/rr*Hh;
  const line=s=>s.map((v,i)=>v==null?"":`${(i&&s[i-1]!=null)?"L":"M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const area=`M${X(0).toFixed(1)},${B} `+sale.map((v,i)=>`L${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ")+` L${X(n-1).toFixed(1)},${B} Z`;
  let grid="";const step=(hi-lo)/3;for(let g=0;g<=3;g++){const tv=lo+step*g,y=Y(tv).toFixed(1);
    grid+=`<line x1="${L}" y1="${y}" x2="${Rr}" y2="${y}" stroke="#F1F2EC"/><text class="axt" x="${L-7}" y="${(+y+3).toFixed(1)}" text-anchor="end">${tv.toFixed(0)}</text>`;}
  let xt="";const asof=new Date(ASOF+"T00:00:00");
  for(let j=0;j<4;j++){const i=Math.round(j/3*(n-1));const d=new Date(asof);
    if(wk)d.setDate(d.getDate()-7*(n-1-i));else d.setMonth(d.getMonth()-(n-1-i));
    xt+=`<text class="axt" x="${X(i).toFixed(1)}" y="${B+15}" text-anchor="middle">'${String(d.getFullYear()).slice(2)}.${d.getMonth()+1}</text>`;}
  const ycy=((T0+B)/2).toFixed(0);
  svg.innerHTML=`<defs><linearGradient id="gA" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#B65F5A" stop-opacity=".24"/><stop offset="1" stop-color="#B65F5A" stop-opacity="0"/></linearGradient></defs>`
    +grid+`<line x1="${L}" y1="${B}" x2="${Rr}" y2="${B}" stroke="#D7D8D0"/>`
    +`<path id="trArea" d="${area}" fill="url(#gA)" opacity="0" style="transition:opacity .6s ease .15s"/>`
    +`<path id="trJeon" class="draw" d="${line(jeon)}" fill="none" stroke="#5A7CA0" stroke-width="1.7" stroke-dasharray="4 3"/>`
    +`<path id="trSale" class="draw" d="${line(sale)}" fill="none" stroke="#B65F5A" stroke-width="2.2"/>`
    +`<circle id="trDotS" cx="${X(n-1)}" cy="${Y(sale[n-1])}" r="4" fill="#B65F5A" stroke="#fff" stroke-width="1.4" opacity="0" style="transition:opacity .3s ease .7s"/>`
    +`<circle id="trDotJ" cx="${X(n-1)}" cy="${Y(jeon[n-1])}" r="3.2" fill="#5A7CA0" stroke="#fff" stroke-width="1.2" opacity="0" style="transition:opacity .3s ease .7s"/>`
    +xt+`<text class="axtitle" x="${((L+Rr)/2).toFixed(0)}" y="${_trH-6}" text-anchor="middle">시점(${wk?"주간 지수":"월간 지수"})</text>`
    +`<text class="axtitle" x="14" y="${ycy}" text-anchor="middle" transform="rotate(-90 14 ${ycy})">가격지수 (2022.1.10=100)</text>`
    +`<line class="vx" x1="${L}" x2="${L}" y1="${T0}" y2="${B}" stroke="#B9BBB0" stroke-dasharray="3 3" opacity="0"/>`
    +`<circle class="vd1" r="3" fill="#B65F5A" opacity="0"/><circle class="vd2" r="2.6" fill="#5A7CA0" opacity="0"/>`;
  // ── 그려지는 애니메이션 (stroke-dashoffset) ──
  ["trSale","trJeon"].forEach(id=>{const p=svg.querySelector("#"+id);const Ln=p.getTotalLength();
    p.style.setProperty("--L",Ln);p.style.strokeDasharray=Ln;p.style.strokeDashoffset=Ln;p.getBoundingClientRect();
    p.style.transition="stroke-dashoffset .85s ease";p.style.strokeDashoffset="0";});
  requestAnimationFrame(()=>{svg.querySelector("#trArea").style.opacity="1";svg.querySelector("#trDotS").style.opacity="1";svg.querySelector("#trDotJ").style.opacity="1";});
  // 호버 크로스헤어
  const vtip=document.getElementById("vtip"),vx=svg.querySelector(".vx"),vd1=svg.querySelector(".vd1"),vd2=svg.querySelector(".vd2");
  svg.onmousemove=e=>{const b=svg.getBoundingClientRect();const ux=(e.clientX-b.left)/b.width*620;let i=Math.round((ux-L)/W*(n-1));i=Math.max(0,Math.min(n-1,i));
    const x=X(i);vx.setAttribute("x1",x);vx.setAttribute("x2",x);vx.style.opacity="1";
    if(sale[i]!=null){vd1.setAttribute("cx",x);vd1.setAttribute("cy",Y(sale[i]));vd1.style.opacity="1";}else vd1.style.opacity="0";
    if(jeon[i]!=null){vd2.setAttribute("cx",x);vd2.setAttribute("cy",Y(jeon[i]));vd2.style.opacity="1";}else vd2.style.opacity="0";
    vtip.innerHTML=`매매 <b>${sale[i]==null?"-":sale[i]}</b> · 전세 <b style="color:#5A7CA0">${jeon[i]==null?"-":jeon[i]}</b>`;
    let lx=e.clientX-b.left+12;if(lx>b.width-150)lx-=160;vtip.style.left=lx+"px";vtip.style.top="2px";vtip.style.opacity="1";};
  svg.onmouseleave=()=>{vx.style.opacity="0";vd1.style.opacity="0";vd2.style.opacity="0";vtip.style.opacity="0";};}

// ── 지역 비교 모드 (여러 지역 가격지수 오버레이 · 월간 통일) ──
const CMPC={gn3:"#B65F5A",seoul:"#C28A4E",gg:"#5A7CA0",incheon:"#7E9A83",daegu:"#9A7AA8",busan:"#C2A24E"};
let cmpMode=false,cmpSel=["gn3","gg","busan"],cmpMet="mm";
function toMonthly(series,weekly){const s=(series||[]).filter(v=>v!=null);
  if(!weekly)return s.slice();
  const n=s.length,asof=new Date(ASOF+"T00:00:00"),bk={},od=[];
  for(let i=0;i<n;i++){const d=new Date(asof);d.setDate(d.getDate()-7*(n-1-i));const k=d.getFullYear()+"-"+d.getMonth();if(!(k in bk))od.push(k);bk[k]=s[i];}
  return od.map(k=>bk[k]);}
function cmpSeries(rk,met){let raw;
  if(SUDO.has(rk)){const tk=TREND[rk]||{};raw=met==="js"?tk.jeonse:tk.sale;return toMonthly(raw,true);}
  const o=(LOCAL[rk]||{}).others||{};raw=met==="js"?o.jeonse:o.sale;return toMonthly(raw,false);}
function drawCompare(){
  document.getElementById("trTitle").textContent="지역 비교 · "+(cmpMet==="js"?"전세":"매매")+" 지수";
  const svg=document.getElementById("trChart");svg.onmousemove=null;svg.onmouseleave=null;
  document.getElementById("vtip").style.opacity="0";
  const pm=period==="1y"?12:period==="3y"?36:1e9;
  let series=cmpSel.map(k=>({k,c:CMPC[k],nm:RNAME[k],s:cmpSeries(k,cmpMet)})).filter(o=>o.s&&o.s.length>=2);
  if(!series.length){svg.innerHTML='<text class="axt" x="310" y="'+(_trH/2).toFixed(0)+'" text-anchor="middle">비교할 지역을 선택하세요</text>';return;}
  let K=Math.min(...series.map(o=>o.s.length));K=Math.min(K,pm);
  series=series.map(o=>({k:o.k,c:o.c,nm:o.nm,s:o.s.slice(-K)}));
  const L=52,Rr=606,T0=14,B=_trB,W=Rr-L,Hh=B-T0,n=K;
  let all=[];series.forEach(o=>all=all.concat(o.s));
  let dmn=Math.min(...all),dmx=Math.max(...all);const pad=(dmx-dmn)*0.14||1,lo=dmn-pad,hi=dmx+pad,rr=(hi-lo)||1;
  const X=i=>L+(n<=1?0:i/(n-1)*W),Y=v=>B-(v-lo)/rr*Hh;
  let grid="";const step=(hi-lo)/3;for(let g=0;g<=3;g++){const tv=lo+step*g,y=Y(tv).toFixed(1);
    grid+=`<line x1="${L}" y1="${y}" x2="${Rr}" y2="${y}" stroke="#F1F2EC"/><text class="axt" x="${L-7}" y="${(+y+3).toFixed(1)}" text-anchor="end">${tv.toFixed(0)}</text>`;}
  let xt="";const asof=new Date(ASOF+"T00:00:00");
  for(let j=0;j<4;j++){const i=Math.round(j/3*(n-1));const d=new Date(asof);d.setMonth(d.getMonth()-(n-1-i));
    xt+=`<text class="axt" x="${X(i).toFixed(1)}" y="${B+15}" text-anchor="middle">'${String(d.getFullYear()).slice(2)}.${d.getMonth()+1}</text>`;}
  let lines="";series.forEach(o=>{const d=o.s.map((v,i)=>`${i?"L":"M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
    lines+=`<path d="${d}" fill="none" stroke="${o.c}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    const lx=X(n-1),ly=Y(o.s[n-1]);
    lines+=`<circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="3.4" fill="${o.c}" stroke="#fff" stroke-width="1.3"/><text class="axt" x="${(lx+6).toFixed(1)}" y="${(ly+3).toFixed(1)}" fill="${o.c}" font-weight="700">${o.s[n-1].toFixed(0)}</text>`;});
  const ycy=((T0+B)/2).toFixed(0);
  svg.innerHTML=grid+`<line x1="${L}" y1="${B}" x2="${Rr}" y2="${B}" stroke="#D7D8D0"/>`+xt
    +`<text class="axtitle" x="${((L+Rr)/2).toFixed(0)}" y="${_trH-6}" text-anchor="middle">시점(월간)</text>`
    +`<text class="axtitle" x="14" y="${ycy}" text-anchor="middle" transform="rotate(-90 14 ${ycy})">가격지수 (2022.1.10=100)</text>`+lines;}
function drawTrend(){if(cmpMode)drawCompare();else drawChart();}
function drawCmpChips(){document.getElementById("cmpChips").innerHTML=ORDER.map(k=>{const on=cmpSel.includes(k),c=CMPC[k];
  return `<span class="cmpchip ${on?"on":""}" data-k="${k}" style="${on?`border-color:${c};background:${c}14`:""}"><span class="cd" style="${on?`background:${c}`:""}"></span>${RNAME[k]}</span>`;}).join("");
  document.querySelectorAll("#cmpChips .cmpchip").forEach(c=>c.onclick=()=>cmpToggle(c.dataset.k));}
function cmpToggle(k){const i=cmpSel.indexOf(k);
  if(i>=0){if(cmpSel.length<=1)return;cmpSel.splice(i,1);}
  else{if(cmpSel.length>=3)return;cmpSel.push(k);}
  drawCmpChips();drawCompare();}

function updateNote(){const ph=!SUDO.has(region);
  document.getElementById("note").innerHTML=(ph
    ?"인천·부산·대구는 구별 KB 월간 가격지수 · 지도 형태는 예시 배치(실제 구 경계 아님) · 거래(실거래)는 지방 미수집(–) · 군·섬 지역 제외"
    :"우상단 미니 한반도/칩으로 지역 이동 · 시군구는 표본 작아 주간 거래 변동 큼")
    +" · 매매·전세Δ=KB 월간 가격지수 전월대비, 전세가율=KB 월간, 거래=주간 실거래(평소比=현재주 vs 최근2개월 주당 평균·현재주 제외, 신고지연으로 참고용) · 추이=KB 지수("
    +(ph?"월간":"수도권 주간·지방 월간")+", 2022.1.10=100)";}

function refresh(){drawChips();drawNav();drawLegend();drawMap();drawTable();fitTrendHeight();updateNote();document.getElementById("crName").textContent=RNAME[region];
  document.getElementById("phbadge").hidden=SUDO.has(region);}
function setRegion(k){if(!RNAME[k]||busy)return;busy=true;region=k;
  drawChips();drawNav();document.getElementById("crName").textContent=RNAME[k];
  const svg=document.getElementById("big");svg.style.transformOrigin="50% 46%";svg.style.transition="transform .16s ease, opacity .16s ease";
  svg.style.opacity="0";svg.style.transform="scale(1.12)";
  setTimeout(()=>{drawLegend();drawMap();drawTable();fitTrendHeight();updateNote();
    svg.style.transition="none";svg.style.opacity="0";svg.style.transform="scale(.9)";svg.getBoundingClientRect();
    requestAnimationFrame(()=>requestAnimationFrame(()=>{svg.style.transition="transform .44s cubic-bezier(.18,.7,.3,1), opacity .3s ease";svg.style.opacity="1";svg.style.transform="scale(1)";}));
    setTimeout(()=>{busy=false;},480);},190);}
document.querySelectorAll("#periodSeg button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#periodSeg button").forEach(x=>x.classList.remove("on"));b.classList.add("on");period=b.dataset.p;drawTrend();});
document.querySelectorAll("#cmpTog button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#cmpTog button").forEach(x=>x.classList.remove("on"));b.classList.add("on");
  cmpMode=(b.dataset.cm==="cmp");document.getElementById("cmpCtl").hidden=!cmpMode;document.getElementById("trLeg").style.display=cmpMode?"none":"";
  if(cmpMode)drawCmpChips();drawTrend();});
document.querySelectorAll("#cmpMet button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#cmpMet button").forEach(x=>x.classList.remove("on"));b.classList.add("on");cmpMet=b.dataset.m;drawCompare();});
document.querySelectorAll("#metricPills button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#metricPills button").forEach(x=>x.classList.remove("on"));b.classList.add("on");metric=b.dataset.m;drawLegend();drawMap();drawTable();});
document.getElementById("back").onclick=()=>setRegion("seoul");
refresh();
setTimeout(fitTrendHeight,220);setTimeout(fitTrendHeight,750);   // 폰트·레이아웃 안정 후 재맞춤
(function(){let _rt;window.addEventListener("resize",function(){clearTimeout(_rt);_rt=setTimeout(fitTrendHeight,180);});})();
(function(){function _fit(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;if(window.frameElement){window.frameElement.style.height=h+"px";window.frameElement.setAttribute("height",h);}}catch(e){}}window.addEventListener("load",_fit);setTimeout(_fit,150);setTimeout(_fit,600);setTimeout(_fit,1500);window.addEventListener("resize",_fit);try{new ResizeObserver(_fit).observe(document.body);}catch(e){}})();
</script></body></html>
'''


def _add_months(d, k):
    m = d.month - 1 + k
    y = d.year + m // 12
    return type(d)(y, m % 12 + 1, 1)


def _monthly_series(series, weekly, asof):
    """시계열을 월말값으로 리샘플 → [((y,m), value)...]. weekly면 7일, 아니면 1개월씩 역산."""
    from datetime import timedelta, date as _date
    s = [float(v) for v in (series or []) if v is not None]
    if not s:
        return []
    base = _date(asof.year, asof.month, 1)
    bucket = {}
    n = len(s)
    for i, v in enumerate(s):
        back = n - 1 - i
        if weekly:
            d = asof - timedelta(days=7 * back)
        else:
            d = _add_months(base, -back)
        bucket[(d.year, d.month)] = v
    return [(ym, bucket[ym]) for ym in sorted(bucket)]


def _streak_ytd(monthly):
    """(방향 up:bool|None, 연속개월:int, 26년초대비 %:float|None)."""
    vals = [v for _, v in monthly]
    if len(vals) < 2:
        return (None, 0, None)
    up = vals[-1] >= vals[-2]
    cnt = 1
    for i in range(len(vals) - 2, 0, -1):
        if (vals[i] >= vals[i - 1]) == up:
            cnt += 1
        else:
            break
    base = next((v for (ym, v) in monthly if ym == (2026, 1)), None)
    ytd = (vals[-1] / base - 1) * 100 if base else None
    return (up, cnt, ytd)


def _streak_card(name, su, sc, sy, ju, jc, jy):
    def badge(u, c):
        if u is None or c == 0:
            return '<span class="re-strk-bdg fl">— 자료</span>'
        cls = "up" if u else "dn"
        return f'<span class="re-strk-bdg {cls}">{"▲" if u else "▼"} {c}개월</span>'
    def yt(y):
        if y is None:
            return '<span class="re-strk-ytd fl">—</span>'
        cls = "up" if y >= 0 else "dn"
        return f'<span class="re-strk-ytd {cls}">{"+" if y >= 0 else ""}{y:.1f}%</span>'
    return (f'<div class="re-strk-c"><div class="re-strk-rg">{name}</div>'
            f'<div class="re-strk-row"><span class="t">매매</span>{badge(su, sc)}{yt(sy)}</div>'
            f'<div class="re-strk-row"><span class="t">전세</span>{badge(ju, jc)}{yt(jy)}</div></div>')


def _wb_pct(v, dec=2):
    """전월대비 % 포맷. None이면 '—'. 음수는 유니코드 마이너스(−)."""
    if not isinstance(v, (int, float)):
        return "—"
    sign = "+" if v >= 0 else "−"
    return f"{sign}{abs(v):.{dec}f}%"


def _watchlist_signals():
    """지도 위 '주목 지역' 밴드용 신호 4종. 서울·경기·인천·대구·부산 구를 한 풀로 모아
    급등/약세/거래급증/괴리를 계산한다.
      · mm/js = KB 월간 가격지수 전월대비%(수도권·지방 동일 기준) → 통합 랭킹 안전.
      · vc(거래 전주비%) = 수도권 실거래만 존재 → 거래급증은 수도권 한정.
    각 구는 {'reg'(권역),'nm'(구명),'mm','js','vc'}. 같은 구명(중구 등) 충돌은 reg로 구분."""
    pool = []
    try:
        regions = _merged_regions()
    except Exception:
        regions = _GEO
    for d in (regions or []):
        sd = d.get("sd")
        reg = "서울" if sd == "seoul" else ("경기" if sd == "gg" else None)
        if reg is None:
            continue
        pool.append({"reg": reg, "nm": d.get("n") or d.get("sl") or "",
                     "mm": d.get("mm"), "js": d.get("js"),
                     "v": d.get("v"), "vavg": d.get("vavg")})
    _NM = {"incheon": "인천", "busan": "부산", "daegu": "대구"}
    local = _fetch_local() or {}
    for rk, rv in local.items():
        reg = (rv or {}).get("name") or _NM.get(rk, rk)
        for gname, gv in ((rv or {}).get("gu") or {}).items():
            if not isinstance(gv, dict):
                continue
            pool.append({"reg": reg, "nm": gname,
                         "mm": gv.get("mm"), "js": gv.get("js"),
                         "v": None, "vavg": None})

    def _num(x, k):
        return isinstance(x.get(k), (int, float))

    # 거래 활발도 = 평소比 = (현재주 거래수 v / 평소 주당평균 vavg − 1)×100.
    # 지도 구별 테이블과 동일 지표. 전주比(vc)는 신고지연으로 최신주 표본이 늘
    # 결손 → 대부분 ≤0이라 '급증'이 안 잡히던 문제를 평소比로 통일해 해소.
    V_FLOOR = 2   # 단일 거래로 배수가 튀는 초박형 시군구 제외(노이즈 컷)
    for x in pool:
        v, va = x.get("v"), x.get("vavg")
        x["vr"] = ((v / va - 1) * 100
                   if isinstance(v, (int, float)) and isinstance(va, (int, float))
                   and va > 0 and v >= V_FLOOR else None)

    mm = [x for x in pool if _num(x, "mm")]
    vv = [x for x in pool if _num(x, "vr")]
    gp = [x for x in pool if _num(x, "mm") and _num(x, "js")]
    return {
        "surge": sorted(mm, key=lambda x: x["mm"], reverse=True)[:3],
        "weak": sorted(mm, key=lambda x: x["mm"])[:3],
        "vsurge": sorted(vv, key=lambda x: x["vr"], reverse=True)[:3],
        "gap": sorted(gp, key=lambda x: abs(x["mm"] - x["js"]), reverse=True)[:3],
    }


def _wb_head(title, dot, sub=""):
    s = f'<span class="sub">{sub}</span>' if sub else ""
    return (f'<div class="re-wb-h"><span class="dot" style="background:{dot}"></span>'
            f'{title}{s}</div>')


def _wb_rg(x):
    return f'<span class="rg"><em>{x["reg"]}</em>{x["nm"]}</span>'


def _wb_mover_card(title, dot, items):
    """매매 급등/약세 카드 — 값 부호로 색을 정해 정직하게 표시(상승=red·하락=blue)."""
    if not items:
        return (f'<div class="re-wb-c">{_wb_head(title, dot)}'
                f'<div class="re-wb-r lead"><span class="rg">자료 없음</span></div></div>')
    rows = ""
    for i, x in enumerate(items):
        cls = "lead" if i == 0 else "sub2"
        vc = "up" if x["mm"] >= 0 else "dn"
        rows += (f'<div class="re-wb-r {cls}">{_wb_rg(x)}'
                 f'<span class="v {vc}">{_wb_pct(x["mm"])}</span></div>')
    return f'<div class="re-wb-c">{_wb_head(title, dot)}{rows}</div>'


def _wb_vol_label(x):
    """평소比(vr) → '평소 2.3×' / '평소 +40%' / '평소 수준' / '평소 −41%' (지도 volCtx와 동일)."""
    p = x.get("vr")
    if p is None:
        return "평소 —"
    va = x.get("vavg") or 0
    m = (x.get("v") / va) if va else None
    if abs(p) < 15:
        return "평소 수준"
    if m is not None and m >= 2:
        return f"평소 {m:.1f}×"
    if p > 0:
        return f"평소 +{round(p)}%"
    return f"평소 {round(p)}%"


def _wb_vol_card(title, dot, items):
    """거래 활발도 카드 — 수도권 실거래 평소比(현재주 vs 최근2개월 주당평균)."""
    sub = "수도권 · 평소比"
    if not items:
        return (f'<div class="re-wb-c">{_wb_head(title, dot, sub)}'
                f'<div class="re-wb-r lead"><span class="rg">자료 없음</span></div></div>')
    rows = ""
    for i, x in enumerate(items):
        cls = "lead" if i == 0 else "sub2"
        rows += (f'<div class="re-wb-r {cls}">{_wb_rg(x)}'
                 f'<span class="v sg">{_wb_vol_label(x)}</span></div>')
    return f'<div class="re-wb-c">{_wb_head(title, dot, sub)}{rows}</div>'


def _wb_gap_card(title, dot, items):
    """매매·전세 괴리 카드 — |매매Δ−전세Δ| 큰 순. 매매>전세=매매주도, 반대=전세주도.
    선두만 매·전 상세를 보이고 2·3위는 칩만(카드 높이 균형)."""
    if not items:
        return (f'<div class="re-wb-c">{_wb_head(title, dot)}'
                f'<div class="re-wb-r lead"><span class="rg">자료 없음</span></div></div>')
    rows = ""
    for i, x in enumerate(items):
        lead = (x["mm"] >= x["js"])
        pill = ('<span class="re-wb-pill up">매매주도</span>' if lead
                else '<span class="re-wb-pill dn">전세주도</span>')
        cls = "lead" if i == 0 else "sub2"
        rows += f'<div class="re-wb-r {cls}">{_wb_rg(x)}{pill}</div>'
        if i == 0:
            rows += (f'<div class="re-wb-gap">매 {_wb_pct(x["mm"])} · '
                     f'전 {_wb_pct(x["js"])}</div>')
    return f'<div class="re-wb-c">{_wb_head(title, dot)}{rows}</div>'


def _render_watchlist_band():
    """지도 위 '주목 지역' 밴드 — 5개 권역 구를 한눈에 스캔(급등/약세/거래급증/괴리).
    iframe 바깥 부모 문서에 그려 _RE_CSS 전역 변수를 그대로 쓴다(표시 전용 v1)."""
    sig = _watchlist_signals()
    cards = (_wb_mover_card("매매 급등", "#B65F5A", sig["surge"])
             + _wb_mover_card("매매 약세", "#5A7CA0", sig["weak"])
             + _wb_vol_card("거래 활발도", "#7E9A83", sig["vsurge"])
             + _wb_gap_card("매매·전세 괴리", "#C2A86A", sig["gap"]))
    st.markdown('<div class="re-wb-sec">주목 지역'
                '<span>이번 달 · 전월대비 · 서울·경기·인천·대구·부산 구 단위</span></div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="re-wb">{cards}</div>', unsafe_allow_html=True)
    st.markdown('<div class="re-wb-foot">매매·전세 = KB 월간 가격지수 전월대비 · '
                '거래 활발도 = 수도권 실거래 평소比(현재주 vs 최근2개월 주당 평균 · '
                '지도 테이블과 동일 지표 · 신고지연으로 참고용 · 지방 미수집) · '
                '같은 구명은 앞의 권역으로 구분</div>', unsafe_allow_html=True)


def _render_streak_section():
    """지도 위 고정 섹션 — 6개 지역 × 매매·전세: 월간 연속 상승/하락 + 26년초 대비 %.
    수도권 추이는 KB 주간 → 월말값 리샘플, 지방은 KB 월간 그대로(월 단위 통일)."""
    from datetime import date as _date
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime as _dt
        asof = _dt.now(ZoneInfo("Asia/Seoul")).date()
    except Exception:
        asof = _date.today()
    _g, t = fetch_region_levels()
    local = _fetch_local()
    REG = [("gn3", "강남3구", True), ("seoul", "서울", True), ("gg", "경기", True),
           ("incheon", "인천", False), ("daegu", "대구", False), ("busan", "부산", False)]
    cards = ""
    for key, name, weekly in REG:
        if weekly:
            tr = (t or {}).get(key, {})
            sale, jeon = tr.get("sale"), tr.get("jeonse")
        else:
            o = ((local or {}).get(key) or {}).get("others", {})
            sale, jeon = o.get("sale"), o.get("jeonse")
        su, sc, sy = _streak_ytd(_monthly_series(sale, weekly, asof))
        ju, jc, jy = _streak_ytd(_monthly_series(jeon, weekly, asof))
        cards += _streak_card(name, su, sc, sy, ju, jc, jy)
    st.markdown('<div class="re-strk-sec">가격지수 동향'
                '<span>월간 · 연속 상승/하락 · \u201926년초 대비</span></div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="re-strk">{cards}</div>', unsafe_allow_html=True)


def _map_component(regions, groups, trend, local):
    """지도 탭 C안 컴포넌트(iframe) — 미니 한반도 내비(상시) + 줌 전환 + 6지역 + 구별표 + 추이."""
    import json as _json
    from datetime import date as _date
    D = _json.dumps(regions, ensure_ascii=False, separators=(",", ":"))
    LG = _json.dumps(_LOCAL_GEO, ensure_ascii=False, separators=(",", ":"))
    LC = _json.dumps(local or {}, ensure_ascii=False, separators=(",", ":"))
    TR = _json.dumps({k: (trend or {}).get(k, {}) for k in ("gn3", "seoul", "gg")},
                     ensure_ascii=False, separators=(",", ":"))
    GN3 = _json.dumps(["강남구", "서초구", "송파구"], ensure_ascii=False)
    AS = _json.dumps(_date.today().isoformat())
    return (_MAPC_HTML.replace("__D__", D).replace("__LGEO__", LG)
            .replace("__LOCAL__", LC).replace("__TREND__", TR)
            .replace("__GN3__", GN3).replace("__ASOF__", AS))


def _fetch_local():
    """지방 광역시(인천·부산·대구) 지도 데이터. 세션/DB metrics의 '_local' → 샘플 폴백."""
    m = _resolved_metrics()
    if isinstance(m, dict) and isinstance(m.get("_local"), dict) and m["_local"]:
        return m["_local"]
    return _LOCAL_SAMPLE


def _render_map():
    g, t = fetch_region_levels()
    components.html(_map_component(_merged_regions(), g, t, _fetch_local()),
                    height=1240, scrolling=False)


# ── 지도 탭 추이 차트 (코스피·코스닥 양식 · 매매·전세·전세가율 3종) ──────────
#   증시 '지수' 탭의 대형 차트(_big_index_chart)와 같은 룩: 영역+선 + 호버 십자선.
#   B안 = 포커스(큰 차트 1개) + 미니카드 3개(클릭 시 위에서 크게). 기간 2020~.
#   데이터는 지표와 동일한 DB 시계열(sale/jeonse/jr)을 재사용한다(별도 수집 없음).
#   매매·전세=KB 주간, 전세가율=KB 월간 → 카드마다 '주간/월간' 칩으로 명시(단위 통일).
_TREND_META = {
    "sale":   {"cad": "week",  "dp": "idx", "col": "#B65F5A", "sub": "서울 · KB"},
    "jeonse": {"cad": "week",  "dp": "idx", "col": "#5A7CA0", "sub": "서울 · KB"},
    "jr":     {"cad": "month", "dp": "pp",  "col": "#6E8FA8", "sub": "서울 · KB"},
}
_TREND_ORDER = ["sale", "jeonse", "jr"]


def _trend_series_3(data):
    """지표 시계열(list[{key,label,...,series}])에서 매매·전세·전세가율 3종만
    추려 추이 차트용 dict 리스트로 변환. 시계열 2개 미만은 제외."""
    by = {it.get("key"): it for it in (data or [])}
    out = []
    for k in _TREND_ORDER:
        it = by.get(k)
        if not it:
            continue
        series = [float(v) for v in (it.get("series") or []) if v is not None]
        if len(series) < 2:
            continue
        meta = _TREND_META[k]
        out.append({
            "k": k,
            "lab": it.get("label", k),
            "sub": meta["sub"],
            "cad": meta["cad"],
            "dp": meta["dp"],
            "unit": it.get("unit", ""),
            "col": it.get("col", meta["col"]),
            "real": [round(v, 2) for v in series],
        })
    return out


def _trend_component(inds, asof):
    import json as _json
    return (_TREND_HTML
            .replace("__INDS__", _json.dumps(inds, ensure_ascii=False))
            .replace("__ASOF__", asof))


def _render_trend_charts(data):
    """지도 탭 하단 추이 섹션. 데이터 없으면 캡션만."""
    from datetime import date
    inds = _trend_series_3(data)
    if not inds:
        st.caption("추이 데이터가 아직 없어요. 매일 아침 자동 수집 후 표시됩니다.")
        return
    asof = date.today().strftime("%Y-%m-%d")
    components.html(_trend_component(inds, asof), height=508, scrolling=False)
    st.markdown(foot_row(
        "KB 주간·월간",
        "매매·전세가격지수(KB 주간) · 전세가율(KB 월간) · 카드를 누르면 위에서 크게 · "
        "기간 토글 동기화 · 코스피·코스닥 차트와 동일 양식"), unsafe_allow_html=True)


_TREND_HTML = r'''<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{--bg:#FCFCFA;--card:#fff;--ink:#34352f;--muted:#9a9b92;--line:#ECEDE7;--line2:#DEDED7;
 --sage:#A7BBA9;--sage2:#7E9A83;--up:#B65F5A;--dn:#5A7CA0;
 --kfont:'Pretendard',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--kfont);font-size:14px;
 -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
.box{padding:2px 1px 6px}
.top{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;margin-bottom:11px}
.top .cap{font-size:12px;color:var(--muted)}
.seg{display:inline-flex;border:1px solid var(--line2);border-radius:8px;overflow:hidden;background:var(--card)}
.seg button{border:none;background:none;padding:6px 13px;font-size:12px;color:var(--muted);cursor:pointer;
 border-right:1px solid var(--line);font-family:var(--kfont)}
.seg button:last-child{border-right:none}
.seg button.on{background:#EEF1EC;color:var(--ink);font-weight:700}
.cad{display:inline-block;font-size:10px;font-weight:800;letter-spacing:.02em;border-radius:6px;padding:2px 6px}
.cad.month{background:#EEF1EC;color:#5E7363}.cad.week{background:#F3EEE6;color:#8A6E45}
.delta{font-size:12px;font-weight:800;padding:3px 9px;border-radius:7px;white-space:nowrap}
.delta.up{color:var(--up);background:#FBEEED}.delta.dn{color:var(--dn);background:#EAF0F7}.delta.fl{color:var(--muted);background:#F1F2EC}
.hero{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:15px 17px 11px;margin-bottom:13px}
.hero-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin-bottom:5px}
.hero-lab{font-size:12.5px;font-weight:600;color:var(--muted);display:flex;gap:7px;align-items:center}
.hero-val{font-size:30px;font-weight:800;letter-spacing:-.03em;line-height:1;margin-top:3px}
.hero-val .u{font-size:14px;font-weight:600;color:var(--muted);margin-left:3px}
.minirow{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.mini{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:10px 12px 7px;cursor:pointer;
 transition:transform .16s,box-shadow .16s,border-color .16s}
.mini:hover{transform:translateY(-2px);box-shadow:0 6px 16px rgba(52,53,47,.08);border-color:var(--sage)}
.mini.on{border-color:var(--sage2);box-shadow:inset 0 0 0 1.5px var(--sage2)}
.mini .ml{font-size:11px;font-weight:600;color:var(--muted);display:flex;gap:5px;align-items:center}
.mini .mv{font-size:16px;font-weight:800;letter-spacing:-.02em;margin:3px 0 4px}
.mini .mv .u{font-size:9.5px;color:var(--muted);margin-left:1px}
.mini .delta{font-size:10px;padding:1px 6px}
.chart{position:relative;width:100%}
.chart svg{display:block;width:100%;overflow:visible}
.axis{font-size:9.5px;fill:var(--muted);font-family:var(--kfont)}
.tip{position:absolute;pointer-events:none;background:#fff;border:1px solid var(--line2);border-radius:8px;
 padding:6px 9px;font-size:11.5px;box-shadow:0 6px 18px rgba(52,53,47,.13);opacity:0;transform:translateY(3px);
 transition:opacity .12s,transform .12s;white-space:nowrap;z-index:6}
.tip b{font-weight:800}.tip .d{color:var(--muted);font-size:10.5px}
@media(max-width:680px){.minirow{grid-template-columns:repeat(3,1fr)}}
</style></head><body><div class="box">
  <div class="top">
    <div class="cap">KB 가격지수 실데이터 · 마우스 올리면 십자선 · 기간 2020~</div>
    <div class="seg" id="period">
      <button data-p="1Y">1년</button><button data-p="3Y">3년</button><button data-p="ALL" class="on">전체</button>
    </div>
  </div>
  <div class="hero">
    <div class="hero-head">
      <div><div class="hero-lab" id="hLab"></div><div class="hero-val" id="hVal"></div></div>
      <div class="delta" id="hDelta"></div>
    </div>
    <div class="chart" id="hChart"></div>
  </div>
  <div class="minirow" id="miniRow"></div>
</div>
<script>
const IND=__INDS__;
const ASOF=new Date("__ASOF__T00:00:00");
const MON=["1월","2월","3월","4월","5월","6월","7월","8월","9월","10월","11월","12월"];
const DAYS={"1Y":365,"3Y":1095,"ALL":1e9};
let period="ALL",focusK=IND.length?IND[0].k:null;
function byK(k){return IND.find(d=>d.k===k);}
function makeSeries(ind,p){
 const step=ind.cad==="month"?30:7;
 const need=p==="ALL"?ind.real.length:Math.min(ind.real.length,Math.round(DAYS[p]/step)+1);
 const vals=ind.real.slice(-need);
 return vals.map((v,i)=>({t:new Date(ASOF.getTime()-(vals.length-1-i)*step*86400000),v}));
}
function fmtV(ind,v){return (Math.round(v*10)/10).toFixed(1);}
function deltaTxt(ind,pts){const a=pts[0].v,b=pts[pts.length-1].v;
 if(ind.dp==="pp"){const d=b-a;return{cls:d>0.05?"up":d<-0.05?"dn":"fl",txt:(d>=0?"+":"")+(Math.round(d*10)/10)+"p"};}
 const d=(b-a)/a*100;return{cls:d>0.05?"up":d<-0.05?"dn":"fl",txt:(d>=0?"+":"")+(Math.round(d*10)/10)+"%"};}
function drawChart(host,ind,pts,h,longR){
 const W=600,PAD={l:4,r:4,t:8,b:18};
 const xs=i=>PAD.l+i/(pts.length-1)*(W-PAD.l-PAD.r);
 const lo=Math.min.apply(null,pts.map(p=>p.v)),hi=Math.max.apply(null,pts.map(p=>p.v));
 const span=(hi-lo)||1;const y0=lo-span*0.12,y1=hi+span*0.12;
 const ys=v=>PAD.t+(1-(v-y0)/(y1-y0))*(h-PAD.t-PAD.b);
 const col=ind.col;
 let path=pts.map((p,i)=>(i?"L":"M")+xs(i).toFixed(1)+" "+ys(p.v).toFixed(1)).join(" ");
 let area=path+" L"+xs(pts.length-1).toFixed(1)+" "+(h-PAD.b)+" L"+xs(0).toFixed(1)+" "+(h-PAD.b)+" Z";
 let tk="",last=null;
 pts.forEach((p,i)=>{const key=longR?p.t.getFullYear():p.t.getMonth();
  if(key!==last){last=key;const x=xs(i);if(x>12&&x<W-12){
   const lab=longR?("'"+String(p.t.getFullYear()).slice(2)):MON[p.t.getMonth()];
   tk+='<text class="axis" x="'+x.toFixed(1)+'" y="'+(h-5)+'" text-anchor="middle">'+lab+'</text>';}}});
 host.innerHTML='<svg viewBox="0 0 '+W+' '+h+'" preserveAspectRatio="none" style="height:'+h+'px">'
  +'<path d="'+area+'" fill="'+col+'" opacity="0.11"/>'
  +'<path d="'+path+'" fill="none" stroke="'+col+'" stroke-width="2" stroke-linejoin="round"/>'
  +'<line class="vx" x1="0" x2="0" y1="'+PAD.t+'" y2="'+(h-PAD.b)+'" stroke="#B9BBB0" stroke-width="1" stroke-dasharray="3 3" opacity="0"/>'
  +'<circle class="cp" r="3.4" fill="'+col+'" opacity="0"/>'+tk+'</svg>';
 const svg=host.querySelector("svg"),vx=host.querySelector(".vx"),cp=host.querySelector(".cp");
 let tip=host.querySelector(".tip");if(!tip){tip=document.createElement("div");tip.className="tip";host.appendChild(tip);}
 svg.onmousemove=e=>{const r=svg.getBoundingClientRect();const px=(e.clientX-r.left)/r.width*W;
  let i=Math.round((px-PAD.l)/((W-PAD.l-PAD.r))*(pts.length-1));i=Math.max(0,Math.min(pts.length-1,i));
  const x=xs(i),yv=ys(pts[i].v);
  vx.setAttribute("x1",x);vx.setAttribute("x2",x);vx.setAttribute("opacity","1");
  cp.setAttribute("cx",x);cp.setAttribute("cy",yv);cp.setAttribute("opacity","1");
  const d=pts[i].t;tip.innerHTML="<b>"+fmtV(ind,pts[i].v)+ind.unit+"</b> <span class=\"d\">"+d.getFullYear()+"."+String(d.getMonth()+1).padStart(2,"0")+"</span>";
  tip.style.opacity="1";tip.style.transform="translateY(0)";
  let tx=(x/W)*r.width+10;if(tx>r.width-110)tx-=120;tip.style.left=tx+"px";tip.style.top=(yv/h*r.height-30)+"px";};
 svg.onmouseleave=()=>{vx.setAttribute("opacity","0");cp.setAttribute("opacity","0");tip.style.opacity="0";};
}
function render(){
 const longR=period!=="1Y";
 document.getElementById("miniRow").innerHTML=IND.map(ind=>{const pts=makeSeries(ind,period);const dt=deltaTxt(ind,pts);
  return '<div class="mini '+(ind.k===focusK?"on":"")+'" data-k="'+ind.k+'"><div class="ml"><span class="cad '+ind.cad+'">'+(ind.cad==="month"?"월간":"주간")+'</span>'+ind.lab+'</div>'
   +'<div class="mv">'+fmtV(ind,ind.real[ind.real.length-1])+'<span class="u">'+ind.unit+'</span></div>'
   +'<div class="delta '+dt.cls+'">'+dt.txt+'</div></div>';}).join("");
 document.querySelectorAll(".mini").forEach(el=>el.onclick=()=>{focusK=el.dataset.k;render();});
 const ind=byK(focusK);if(!ind)return;const pts=makeSeries(ind,period);const dt=deltaTxt(ind,pts);
 document.getElementById("hLab").innerHTML='<span class="cad '+ind.cad+'">'+(ind.cad==="month"?"월간":"주간")+'</span>'+ind.lab+' · '+ind.sub;
 document.getElementById("hVal").innerHTML=fmtV(ind,ind.real[ind.real.length-1])+'<span class="u">'+ind.unit+'</span>';
 const hd=document.getElementById("hDelta");hd.className="delta "+dt.cls;hd.textContent=dt.txt;
 drawChart(document.getElementById("hChart"),ind,pts,210,longR);
}
document.querySelectorAll("#period button").forEach(b=>b.onclick=()=>{
 document.querySelectorAll("#period button").forEach(x=>x.classList.remove("on"));b.classList.add("on");period=b.dataset.p;render();});
render();
(function(){function _fit(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;if(window.frameElement){window.frameElement.style.height=h+"px";window.frameElement.setAttribute("height",h);}}catch(e){}}window.addEventListener("load",_fit);setTimeout(_fit,150);setTimeout(_fit,600);setTimeout(_fit,1500);window.addEventListener("resize",_fit);try{new ResizeObserver(_fit).observe(document.body);}catch(e){}})();
</script></body></html>'''


_GROUP_ORDER = [
    ("선행·심리", "시장 방향이 먼저 움직이는 신호"),
    ("가격(동행)", "현재 가격 수준"),
    ("공급·펀더멘털", "중기 수급"),
    ("금융", "구매력·자금조달"),
]


def _delta_html(series, dunit):
    """직전값 대비 변화 → 화살표 칩(빨강=상승/파랑=하락)."""
    if not series or len(series) < 2:
        return ""
    d = series[-1] - series[-2]
    cls = "up" if d > 5e-4 else ("dn" if d < -5e-4 else "fl")
    arr = "▲" if cls == "up" else ("▼" if cls == "dn" else "–")
    mag = abs(d)
    txt = f"{mag:,.0f}" if dunit == "건" else (f"{mag:.2f}".rstrip("0").rstrip("."))
    return f'<span class="re-delta {cls}">{arr} {txt}{dunit}</span>'


def _market_phase(cards):
    """지표 시리즈로 규칙기반 '시장 국면' 한 줄 요약(비용 0)."""
    by = {c["label"]: c for c in cards}

    def trend(label):
        s = by.get(label, {}).get("series")
        return (s[-1] - s[-2]) if s and len(s) >= 2 else 0

    seg = []
    if "주간 실거래량(수도권)" in by:
        d = trend("주간 실거래량(수도권)")
        seg.append("거래 " + ("회복세" if d > 0 else "둔화" if d < 0 else "보합"))
    if "매매 주간지수(서울)" in by:
        d = trend("매매 주간지수(서울)")
        seg.append("가격 " + ("상승" if d > 0 else "하락" if d < 0 else "보합"))
    if "매수우위지수" in by:
        v = by["매수우위지수"]["series"][-1]
        seg.append("심리 " + ("매수우위" if v >= 100 else "매도우위"))
    if "미분양(전국)" in by:
        d = trend("미분양(전국)")
        seg.append("공급 부담 " + ("완화" if d < 0 else "확대" if d > 0 else "보합"))
    if "주담대 금리(가중평균)" in by:
        d = trend("주담대 금리(가중평균)")
        seg.append("금리 " + ("하락" if d < 0 else "상승" if d > 0 else "보합"))
    spans = '<span style="color:#C9CBC2;margin:0 2px">·</span>'.join(
        f'<span class="seg">{s}</span>' for s in seg)
    return f'<div class="re-phase"><b>시장 국면</b>{spans}</div>'


# ── 지표 추이 차트 (포커스 + 스몰멀티플 · 기간 1M/3M/1Y/5Y) ───────
_INDV2_HTML = r'''<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{--bg:#FCFCFA;--card:#fff;--ink:#34352f;--muted:#9a9b92;--line:#ECEDE7;--line2:#DEDED7;
 --sage:#A7BBA9;--sage2:#7E9A83;--up:#B65F5A;--upT:#FBEEED;--dn:#5A7CA0;--dnT:#EAF0F7;--sum:#F6F7F2;
 --kfont:'Pretendard',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--kfont);font-size:14px;-webkit-font-smoothing:antialiased}
.box{padding:2px 1px 6px}
.cycle{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:15px 17px;margin-bottom:15px}
.cyc-top{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:11px}
.cyc-top .t{font-size:13px;font-weight:800}
.cyc-top .now{font-size:12px;color:var(--muted)}.cyc-top .now b{color:var(--up)}
.stages{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:9px}
.stage{text-align:center;font-size:12px;font-weight:700;color:var(--muted);padding:9px 4px;border-radius:10px;background:#F4F5F0;border:1px solid transparent}
.stage.on{background:#FBEEED;color:var(--up);border-color:#E7C9C5}
.stage small{display:block;font-size:9.5px;font-weight:600;color:var(--muted);margin-top:1px}
.stage.on small{color:#B07A75}
.cyc-read{font-size:11px;color:var(--muted);line-height:1.5;margin-top:9px;padding-top:8px;border-top:1px solid var(--line)}.cyc-read b{color:var(--ink)}
.cyc-why{margin-top:10px}
.why-lab{font-size:9.5px;font-weight:700;color:var(--sage2);margin-bottom:6px}
.why-chips{display:flex;flex-wrap:wrap;gap:6px}
.why-chip{display:inline-flex;align-items:center;gap:3px;font-size:11px;font-weight:700;padding:3px 9px;border-radius:999px;border:1px solid var(--line);background:var(--card)}
.why-chip.up{color:var(--up)}.why-chip.dn{color:var(--dn)}.why-chip.fl{color:var(--muted)}
.why-summ{font-size:10.5px;color:var(--muted);margin-top:8px;line-height:1.55}
.why-summ b{font-weight:800;color:var(--ink)}.why-summ b.up{color:var(--up)}.why-summ b.dn{color:var(--dn)}
.cyc-gauge{margin-top:11px}
.cg-lab{font-size:9.5px;font-weight:700;color:var(--sage2);margin-bottom:7px}
.cg-wrap{position:relative}
.cg-track{display:flex;height:9px;border-radius:5px;overflow:hidden}
.cg-zone{height:100%}
.cg-needle{position:absolute;top:-3px;width:2.5px;height:15px;background:var(--ink);border-radius:2px;transform:translateX(-50%);box-shadow:0 0 0 2px var(--card)}
.cg-ticks{position:relative;height:12px;margin-top:3px}
.cg-ticks span{position:absolute;font-size:8.5px;font-weight:700;color:var(--muted);transform:translateX(-50%);white-space:nowrap}
.cg-zlab{position:relative;height:13px;margin-top:0}
.cg-zlab span{position:absolute;transform:translateX(-50%);font-size:9px;font-weight:700;color:var(--muted);white-space:nowrap}
.cg-zlab span.on{color:var(--ink)}
.sec{font-size:11.5px;font-weight:700;letter-spacing:.04em;color:var(--muted);text-transform:uppercase;margin:18px 2px 11px;display:flex;align-items:center;gap:9px}
.sec::after{content:"";flex:1;height:1px;background:var(--line)}
.core{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}
.cc{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:13px 14px 11px;transition:border-color .15s,transform .15s,box-shadow .15s}
.cc:hover{border-color:var(--sage);transform:translateY(-1px);box-shadow:0 6px 16px rgba(52,53,47,.07)}
.cc-top{display:flex;align-items:center;justify-content:space-between;gap:6px}
.cc-name{font-size:12.5px;font-weight:800;color:var(--ink)}
.cc-sub{font-size:10px;font-weight:600;color:var(--muted);margin-top:2px}
.cc-val{font-size:23px;font-weight:800;letter-spacing:-.02em;margin:7px 0 2px}
.cc-val .u{font-size:12px;font-weight:600;color:var(--muted);margin-left:2px}
.cc-val .cc-bl{font-size:9.5px;color:var(--muted);font-weight:700;margin-left:6px}
.dchip{display:inline-flex;align-items:baseline;gap:3px;font-size:11px;font-weight:800;padding:2px 7px;border-radius:7px;margin-left:7px;vertical-align:2px}
.dchip.up{color:var(--up);background:var(--upT)}.dchip.dn{color:var(--dn);background:var(--dnT)}.dchip.fl{color:var(--muted);background:#F1F2EC}
.dchip .lab{font-weight:600;font-size:9px;opacity:.85}
.r-d{display:block;font-size:9.5px;font-weight:800;margin-top:1px}
.r-d.up{color:var(--up)}.r-d.dn{color:var(--dn)}.r-d.fl{color:var(--muted)}
.r-d .lab{color:var(--muted);font-weight:600;font-size:8.5px;margin-left:2px}
.cc-interp{font-size:11px;color:var(--muted);line-height:1.5;margin-top:7px}
.mini{width:100%;height:auto;display:block;margin:7px 0 2px;overflow:visible}
.mc-ax{font-size:9px;fill:var(--muted)}
.sig{display:inline-flex;align-items:center;gap:4px;font-size:10.5px;font-weight:800;padding:2px 8px;border-radius:20px;white-space:nowrap}
.sig.up{color:var(--up);background:var(--upT)}.sig.dn{color:var(--dn);background:var(--dnT)}.sig.fl{color:var(--muted);background:#F1F2EC}
.sig.sm{font-size:10px;padding:2px 7px}
.sig .inv{font-size:8.5px;font-weight:700;color:var(--muted);background:#fff;border:1px solid var(--line2);border-radius:4px;padding:0 3px;margin-left:2px}
.grp{margin-top:15px}
.glab{font-size:12px;font-weight:800;color:var(--sage2);margin:0 2px 8px;display:flex;align-items:baseline;gap:7px}
.glab em{font-style:normal;font-size:11px;font-weight:600;color:var(--muted)}
.rows{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.row{display:grid;grid-template-columns:1.5fr 90px 1fr 78px;align-items:center;gap:10px;padding:9px 13px;border-bottom:1px solid var(--line)}
.row:last-child{border-bottom:none}
.row.pend{background:var(--sum)}
.r-name{font-size:12.5px;font-weight:700;color:var(--ink)}
.r-name small{display:block;font-size:10px;font-weight:500;color:var(--muted);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.r-val{font-size:13px;font-weight:800;text-align:right}.r-val .u{font-size:10px;color:var(--muted);font-weight:600;margin-left:1px}
.r-spark{width:100%;height:36px;display:block}
.r-mid{display:block;min-width:0}
.ig{margin-top:9px}
.ig-lab{display:flex;justify-content:space-between;align-items:baseline;font-size:9.5px;color:var(--muted);margin-bottom:3px}
.ig-lab b{color:var(--ink);font-weight:800;font-size:10px}
.ig-track{position:relative;height:7px;background:#EFF0EA;border-radius:4px}
.ig-1y{position:absolute;top:0;bottom:0;background:#D6DFD3;border-radius:4px}
.ig-base{position:absolute;top:-2px;bottom:-2px;width:1.5px;background:#B9BBB0}
.ig-mk{position:absolute;top:50%;width:11px;height:11px;border-radius:50%;border:2px solid #fff;transform:translate(-50%,-50%);box-shadow:0 0 0 1px rgba(52,53,47,.08)}
.ig-ends{display:flex;justify-content:space-between;font-size:8.5px;color:#B7B8B0;margin-top:2px;font-weight:600}
.rg{margin-top:4px;padding:0 1px}
.rg-track{position:relative;height:5px;background:#EFF0EA;border-radius:3px}
.rg-1y{position:absolute;top:0;bottom:0;background:#D6DFD3;border-radius:3px}
.rg-base{position:absolute;top:-1px;bottom:-1px;width:1.5px;background:#C2C4B9}
.rg-mk{position:absolute;top:50%;width:8px;height:8px;border-radius:50%;border:1.5px solid #fff;transform:translate(-50%,-50%)}
.rsig{display:flex;flex-direction:column;align-items:flex-end;gap:2px}
.rg-pct{font-size:8.5px;color:var(--muted);font-weight:700;white-space:nowrap}
.pend-tag{display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:var(--muted);background:#fff;border:1px dashed var(--line2);padding:3px 8px;border-radius:7px}
.row.pend.chk{background:#FCF7EC}
.chk-tag{display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:#9A7B43;background:#FBF5E6;border:1px solid #E7D8B4;padding:3px 8px;border-radius:7px}
.cc.cc-miss{border-style:dashed;background:var(--sum)}
.cc.cc-miss .cc-val{color:var(--muted);font-weight:700}
.foot{font-size:11px;color:var(--muted);margin:14px 2px 2px;line-height:1.5}
.price{display:grid;grid-template-columns:repeat(2,1fr);gap:11px}
.pc{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:13px 15px 11px}
.pc-top{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
.pc-reg{font-size:13px;font-weight:800;color:var(--ink)}
.pc-tag{font-size:10px;font-weight:700;color:var(--muted);white-space:nowrap}
.pc-val{font-size:25px;font-weight:800;letter-spacing:-.02em;margin:8px 0 1px;color:var(--ink)}
.pc-val .u{font-size:12px;font-weight:600;color:var(--muted);margin-left:1px}
.pc-val .lab{font-size:10px;font-weight:800;color:var(--sage2);background:#EEF3EF;border-radius:5px;padding:1px 5px;margin-left:7px;vertical-align:middle}
.pc-mean{font-size:11.5px;color:var(--muted);font-weight:600}
.pc-mean b{color:var(--ink);font-weight:800}
.pc-mom{font-size:10.5px;font-weight:800;margin:0 0 2px}
.pc-mom.up{color:var(--up)}.pc-mom.dn{color:var(--dn)}.pc-mom.fl{color:var(--muted)}
.pc-mom small{font-weight:600;color:var(--muted);font-size:9px;margin-left:2px}
@media(max-width:680px){.core{grid-template-columns:1fr}.row{grid-template-columns:1.3fr 96px 74px}.r-mid{display:none}.price{grid-template-columns:1fr}}
</style></head><body><div class="box">
  <div class="cycle">
    <div class="cyc-top"><span class="t">부동산 사이클 위치</span>
      <span class="now">선행·심리 종합 → 현재 <b id="nowStage"></b></span></div>
    <div class="stages" id="stages"></div>
    <div class="cyc-why" id="cycWhy"></div>
    <div class="cyc-gauge" id="cycGauge"></div>
    <div class="cyc-read" id="cycRead"></div>
  </div>
  <div class="sec" id="priceSec" style="display:none">현재 아파트 매매가격</div>
  <div class="price" id="price"></div>
  <div class="sec">핵심 3 · 지금 시장을 설명하는 지표</div>
  <div class="core" id="core"></div>
  <div class="sec">그룹별 지표</div>
  <div id="groups"></div>
  <div class="foot" id="foot"></div>
</div>
<script>
const IND=__IND__,PEND=__PEND__,G=__G__;
const PRICE=__PRICE__;
const ASOF=new Date("__ASOF__T00:00:00");
const MON=["1월","2월","3월","4월","5월","6월","7월","8월","9월","10월","11월","12월"];
const GORDER=["lead","coin","supply"];
const CORE=["buy","outlook"];
function byK(k){return IND.find(d=>d.k===k);}
function makeSeries(m){const step=m.cad==="month"?30:7;
 const need=Math.min(m.real.length,Math.round(365/step)+1);
 const vals=m.real.slice(-need);
 return vals.map((v,i)=>({t:new Date(ASOF.getTime()-(vals.length-1-i)*step*86400000),v}));}
function fmtV(m,v){const b=Math.abs(m.base||v);if(b>=1000)return Math.round(v).toLocaleString();
 if(b<10)return (Math.round(v*100)/100).toFixed(2);return (Math.round(v*10)/10).toFixed(1);}
function signal(m,pts){const a=pts[0].v,b=pts[pts.length-1].v;let dir=(b-a)/Math.abs(a||1);
 if(m.inv)dir=-dir;
 if(m.baseline!=null){const lvl=(b-m.baseline)/m.baseline;dir=dir*0.6+lvl*0.8;}
 const cls=dir>0.012?"up":dir<-0.012?"dn":"fl";
 return {cls,txt:cls==="up"?"상승 신호":cls==="dn"?"하락 신호":"중립",score:dir};}
function arrow(c){return c==="up"?"▲":c==="dn"?"▼":"●";}
function shortTxt(c){return c==="up"?"상승":c==="dn"?"하락":"중립";}
function monthTicks(pts){let ticks=[],lastM=null;
 pts.forEach((p,i)=>{const mo=p.t.getMonth();if(mo!==lastM){ticks.push({i,mo});lastM=mo;}});
 if(ticks.length>7){const st=Math.ceil(ticks.length/7);ticks=ticks.filter((_,j)=>j%st===0);}
 return ticks;}
function miniChart(m,pts){const W=280,H=64,P={l:4,r:6,t:8,b:17};
 const xs=i=>P.l+i/(pts.length-1)*(W-P.l-P.r);
 const vv=pts.map(p=>p.v);let lo=Math.min.apply(null,vv),hi=Math.max.apply(null,vv);
 if(m.baseline!=null){lo=Math.min(lo,m.baseline);hi=Math.max(hi,m.baseline);}
 const sp=(hi-lo)||1,y0=lo-sp*0.16,y1=hi+sp*0.16;
 const ys=v=>P.t+(1-(v-y0)/(y1-y0))*(H-P.t-P.b);
 const path=pts.map((p,i)=>(i?"L":"M")+xs(i).toFixed(1)+" "+ys(p.v).toFixed(1)).join(" ");
 const area=path+" L"+xs(pts.length-1).toFixed(1)+" "+(H-P.b)+" L"+xs(0).toFixed(1)+" "+(H-P.b)+" Z";
 let bl="";if(m.baseline!=null){const by=ys(m.baseline).toFixed(1);
  bl='<line x1="'+P.l+'" y1="'+by+'" x2="'+(W-P.r)+'" y2="'+by+'" stroke="#C9CBC2" stroke-width="1" stroke-dasharray="4 4"/>';}
 const ax='<line x1="'+P.l+'" y1="'+(H-P.b)+'" x2="'+(W-P.r)+'" y2="'+(H-P.b)+'" stroke="var(--line2)" stroke-width="1"/>';
 let tk=monthTicks(pts).map(t=>{const x=xs(t.i);
  return '<line x1="'+x.toFixed(1)+'" x2="'+x.toFixed(1)+'" y1="'+(H-P.b)+'" y2="'+(H-P.b+3)+'" stroke="#C9CBC2" stroke-width="1"/>'
   +'<text class="mc-ax" x="'+x.toFixed(1)+'" y="'+(H-3)+'" text-anchor="middle">'+MON[t.mo]+'</text>';}).join("");
 return '<svg class="mini" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid meet">'
  +'<path d="'+area+'" fill="'+m.col+'" opacity="0.10"/>'+bl+ax
  +'<path d="'+path+'" fill="none" stroke="'+m.col+'" stroke-width="1.9" stroke-linejoin="round" stroke-linecap="round"/>'
  +tk+'</svg>';}
function deltaOf(m){const r=m.real||[];if(r.length<2)return null;
 const d=r[r.length-1]-r[r.length-2],b=Math.abs(m.base||0),a=Math.abs(d);
 const s=b>=1000?Math.round(a).toLocaleString():b<10?(Math.round(a*100)/100).toFixed(2):(Math.round(a*10)/10).toFixed(1);
 const cls=a<1e-9?"fl":d>0?"up":"dn";
 return {cls,abs:s,signed:(d>0?"+":d<0?"−":"±")+s,lab:m.cad==="month"?"전월":"전주"};}
function arrowD(c){return c==="up"?"▲":c==="dn"?"▼":"±";}
function sparkSVG(m,pts){const W=200,H=38,P={l:3,r:3,t:3,b:13};
 const xs=i=>P.l+(pts.length<=1?0:i/(pts.length-1)*(W-P.l-P.r));
 const vv=pts.map(p=>p.v);let lo=Math.min.apply(null,vv),hi=Math.max.apply(null,vv);
 const sp=(hi-lo)||1,pd=sp*0.14,y0=lo-pd,y1=hi+pd;
 const ys=v=>P.t+(1-(v-y0)/((y1-y0)||1))*(H-P.t-P.b);
 const path=pts.map((p,i)=>(i?"L":"M")+xs(i).toFixed(1)+" "+ys(p.v).toFixed(1)).join(" ");
 const ax='<line x1="'+P.l+'" y1="'+(H-P.b)+'" x2="'+(W-P.r)+'" y2="'+(H-P.b)+'" stroke="var(--line2)" stroke-width="1"/>';
 let tks=monthTicks(pts);
 if(tks.length>3)tks=[tks[0],tks[Math.floor((tks.length-1)/2)],tks[tks.length-1]];
 const tk=tks.map(function(t,j){const x=xs(t.i),an=j===0?"start":j===tks.length-1?"end":"middle";
   return '<line x1="'+x.toFixed(1)+'" x2="'+x.toFixed(1)+'" y1="'+(H-P.b)+'" y2="'+(H-P.b+2.5)+'" stroke="#C9CBC2"/>'
    +'<text class="mc-ax" x="'+x.toFixed(1)+'" y="'+(H-2)+'" text-anchor="'+an+'">'+MON[t.mo]+'</text>';}).join("");
 return '<svg class="r-spark" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid meet">'
  +ax+'<path d="'+path+'" fill="none" stroke="'+m.col+'" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round"/>'+tk+'</svg>';}
function gaugeOf(m){const r=m.real||[];if(r.length<3)return null;
 const lo=Math.min.apply(null,r),hi=Math.max.apply(null,r);if(hi-lo<1e-9)return null;
 const cur=r[r.length-1],pos=Math.max(0,Math.min(1,(cur-lo)/(hi-lo)));
 const yr=makeSeries(m).map(p=>p.v),ylo=Math.min.apply(null,yr),yhi=Math.max.apply(null,yr);
 const top=Math.round((1-pos)*100);
 const tag=pos>=0.99?"전 기간 최고":pos<=0.01?"전 기간 최저":"상위 "+top+"%";
 const baseP=(m.baseline!=null&&m.baseline>=lo&&m.baseline<=hi)?((m.baseline-lo)/(hi-lo))*100:null;
 return {lo,hi,pos:pos*100,tag,baseP,y1l:((ylo-lo)/(hi-lo))*100,y1r:((hi-yhi)/(hi-lo))*100};}
function gaugeHTML(m,g){const base=g.baseP!=null?'<div class="ig-base" style="left:'+g.baseP.toFixed(1)+'%"></div>':'';
 return '<div class="ig"><div class="ig-lab"><span>수위 <b>'+g.tag+'</b></span><span>전 기간 범위</span></div>'
  +'<div class="ig-track"><div class="ig-1y" style="left:'+g.y1l.toFixed(1)+'%;right:'+g.y1r.toFixed(1)+'%"></div>'
  +base+'<div class="ig-mk" style="left:'+g.pos.toFixed(1)+'%;background:'+m.col+'"></div></div>'
  +'<div class="ig-ends"><span>'+fmtV(m,g.lo)+'</span><span>'+fmtV(m,g.hi)+'</span></div></div>';}
function rowGauge(m,g){const base=g.baseP!=null?'<div class="rg-base" style="left:'+g.baseP.toFixed(1)+'%"></div>':'';
 return '<div class="rg"><div class="rg-track"><div class="rg-1y" style="left:'+g.y1l.toFixed(1)+'%;right:'+g.y1r.toFixed(1)+'%"></div>'
  +base+'<div class="rg-mk" style="left:'+g.pos.toFixed(1)+'%;background:'+m.col+'"></div></div></div>';}
function coreCard(m){const pts=makeSeries(m);const s=signal(m,pts);const d=deltaOf(m);const g=gaugeOf(m);
 const bl=m.baseline!=null?'<span class="cc-bl">기준 '+m.baseline+'</span>':'';
 const inv=m.inv?'<span class="inv">역행</span>':'';
 const dc=d?'<span class="dchip '+d.cls+'">'+arrowD(d.cls)+' '+d.abs+'<span class="lab">'+d.lab+'</span></span>':'';
 const sub=m.sub?'<div class="cc-sub">'+m.sub+'</div>':'';
 return '<div class="cc"><div class="cc-top"><span class="cc-name">'+m.lab+'</span>'
  +'<span class="sig '+s.cls+'">'+arrow(s.cls)+' '+s.txt+inv+'</span></div>'+sub
  +'<div class="cc-val">'+fmtV(m,m.base)+'<span class="u">'+m.unit+'</span>'+bl+dc+'</div>'
  +miniChart(m,pts)+(g?gaugeHTML(m,g):'')+'<div class="cc-interp">'+m.interp+'</div></div>';}
function rowHTML(m){const pts=makeSeries(m);const s=signal(m,pts);const d=deltaOf(m);const g=gaugeOf(m);
 const dr=d?'<span class="r-d '+d.cls+'">'+d.signed+'<span class="lab">'+d.lab+'</span></span>':'';
 const pct=g?'<span class="rg-pct">'+g.tag+'</span>':'';
 return '<div class="row"><span class="r-name">'+m.lab+'<small>'+m.sub+'</small></span>'
  +'<span class="r-val">'+fmtV(m,m.base)+'<span class="u">'+m.unit+'</span>'+dr+'</span>'
  +'<span class="r-mid">'+sparkSVG(m,pts)+(g?rowGauge(m,g):'')+'</span>'
  +'<span class="rsig"><span class="sig sm '+s.cls+'">'+arrow(s.cls)+' '+shortTxt(s.cls)+'</span>'+pct+'</span></div>';}
function pendRow(p){const chk=(p.st==="check");
 return '<div class="row pend'+(chk?" chk":"")+'"><span class="r-name">'+p.lab+'<small>'+p.note+'</small></span>'
  +'<span class="r-val">—</span><span></span><span class="'+(chk?"chk-tag":"pend-tag")+'">'+(chk?"점검 필요":"연결예정")+'</span></div>';}
const CORELAB={buy:"매수우위지수",outlook:"매매가격전망지수"};
function coreMissCard(k){return '<div class="cc cc-miss"><div class="cc-top"><span class="cc-name">'+(CORELAB[k]||k)+'</span>'
 +'<span class="chk-tag">점검 필요</span></div><div class="cc-val">—</div>'
 +'<div class="cc-interp">소스 수집 실패 — 데이터가 들어오면 자동으로 채워집니다.</div></div>';}
function renderCore(){const host=document.getElementById("core");
 host.innerHTML=CORE.map(function(k){const m=byK(k);return m?coreCard(m):coreMissCard(k);}).join("");}
function renderGroups(){let html="";
 for(const gk of GORDER){const ms=IND.filter(m=>m.g===gk&&CORE.indexOf(m.k)<0);const ps=PEND.filter(p=>p.g===gk&&CORE.indexOf(p.k)<0);
  if(!ms.length&&!ps.length)continue;
  html+='<div class="grp"><div class="glab">'+G[gk].name+' <em>'+G[gk].desc+'</em></div>'
   +'<div class="rows">'+ms.map(rowHTML).join("")+ps.map(pendRow).join("")+'</div></div>';}
 document.getElementById("groups").innerHTML=html;}
function priceDelta(arr){if(!arr||arr.length<2)return null;
 const cur=arr[arr.length-1],prev=arr[arr.length-2],d=cur-prev;if(!prev)return null;
 const pct=d/prev*100,cls=Math.abs(pct)<0.05?"fl":pct>0?"up":"dn";
 return {cls,pct:(pct>0?"+":pct<0?"−":"±")+Math.abs(pct).toFixed(1),amt:(d>0?"+":d<0?"−":"±")+Math.abs(d).toFixed(2)};}
function priceCard(p){const med=p.med||[],mean=p.mean||[];
 const lastMed=med.length?med[med.length-1]:null;
 const lastMean=mean.length?mean[mean.length-1]:null;
 const m={col:"#7E9A83",baseline:null,base:lastMed,unit:"억",cad:"month",real:med.length?med:mean};
 const pts=makeSeries(m);const dm=priceDelta(med.length?med:mean);
 let big="";
 if(lastMed!=null)big='<div class="pc-val">'+lastMed.toFixed(1)+'<span class="u">억</span><span class="lab">중위</span></div>';
 else if(lastMean!=null)big='<div class="pc-val">'+lastMean.toFixed(1)+'<span class="u">억</span><span class="lab">평균</span></div>';
 const mom=dm?'<div class="pc-mom '+dm.cls+'">전월 '+arrow(dm.cls)+' '+dm.pct+'%<small>'+dm.amt+'억</small></div>':'';
 const meanLine=(lastMean!=null&&lastMed!=null)?'<div class="pc-mean">평균 <b>'+lastMean.toFixed(1)+'억</b></div>':'';
 const chart=pts.length>1?miniChart(m,pts):'';
 return '<div class="pc"><div class="pc-top"><span class="pc-reg">'+p.lab+'</span>'
  +'<span class="pc-tag">아파트 매매 · 월간(KB)</span></div>'+big+mom+meanLine+chart+'</div>';}
function renderPrice(){if(!PRICE||!PRICE.length)return;
 document.getElementById("price").innerHTML=PRICE.map(priceCard).join("");
 document.getElementById("priceSec").style.display="";}
function renderCycle(){const order=["침체기","회복기","상승기","둔화기"];
 const subs={"침체기":"가격↓ 거래↓","회복기":"심리·거래 반등","상승기":"가격·심리 강세","둔화기":"상승폭 축소"};
 const lead=IND.filter(m=>m.g==="lead"||m.k==="jsup");
 const CYCSHORT={buy:"매수우위",outlook:"매매전망",lead50:"선도50",jsup:"전세수급"};
 function cycScore(mb){let sc=0,n=0;lead.forEach(function(m){const r=m.real||[];const off=mb*(m.cad==="month"?1:4);
   if(r.length>off+2){const mm=Object.assign({},m,{real:off?r.slice(0,r.length-off):r});sc+=signal(mm,makeSeries(mm)).score;n++;}});
  return n?sc/n:0;}
 const sc=cycScore(0);
 let cur=lead.length?(sc>0.05?"상승기":sc>0.0?"회복기":sc>-0.05?"둔화기":"침체기"):"회복기";
 document.getElementById("nowStage").textContent=cur;
 document.getElementById("stages").innerHTML=order.map(s=>'<div class="stage '+(s===cur?"on":"")+'">'+s+'<small>'+subs[s]+'</small></div>').join("");
 // 판정 근거 — 기여 칩 + 종합 강도/추세
 const sigs=lead.map(function(m){return {k:m.k,nm:CYCSHORT[m.k]||m.lab,c:signal(m,makeSeries(m)).cls};});
 const chips=sigs.map(function(x){return '<span class="why-chip '+x.c+'">'+arrow(x.c)+' '+x.nm+'</span>';}).join("");
 const ups=sigs.filter(x=>x.c==="up").length,dns=sigs.filter(x=>x.c==="dn").length;
 let mix;if(lead.length&&ups===lead.length)mix='모두 <b class="up">상승 기여</b>';
  else if(lead.length&&dns===lead.length)mix='모두 <b class="dn">하락 기여</b>';
  else mix=ups+'개 <b class="up">상승</b> · '+dns+'개 <b class="dn">하락</b>'+((lead.length-ups-dns)?' · '+(lead.length-ups-dns)+'개 보합':'');
 const dlt=sc-cycScore(1);
 const traj=Math.abs(dlt)<0.005?'<b>유지</b>':(dlt>0?'<b class="up">강화 ↗</b>':'<b class="dn">약화 ↘</b>');
 const scStr=(sc>=0?"+":"−")+Math.abs(sc).toFixed(2);
 document.getElementById("cycWhy").innerHTML='<div class="why-lab">판정 근거 — 선행·심리 '+lead.length+'지표</div>'
  +'<div class="why-chips">'+chips+'</div>'
  +'<div class="why-summ">'+mix+' → 종합 강도 <b>'+scStr+'</b> · 직전 대비 '+traj+'</div>';
 // 종합 강도 위치 게이지(임계 −.05 / 0 / +.05 표시 + needle)
 function stageOf(s){return s>0.05?"상승기":s>0?"회복기":s>-0.05?"둔화기":"침체기";}
 const Z=[["침체기","침체","#5A7CA0",0,33.33],["둔화기","둔화","#A9C0DA",33.33,50],
          ["회복기","회복","#E9BDB8",50,66.67],["상승기","상승","#C16C64",66.67,100]];
 // 구역(침체|둔화|회복|상승) 비율은 33/50/67 그대로 두고, 바깥(침체·상승)이
 // 넓은 점수 범위를 흡수하도록 piecewise 매핑(임계 ±T=±.05 · 양끝 ±GO=±.50).
 const T=0.05,GO=0.50;
 function gPos(s){
   if(s<=-GO)return 0;
   if(s< -T)return (s+GO)/(GO-T)*33.33;      // 침체: -GO..-T → 0..33.33
   if(s<  0)return 33.33+(s+T)/T*16.67;      // 둔화: -T..0  → 33.33..50
   if(s<  T)return 50+s/T*16.67;             // 회복: 0..T   → 50..66.67
   if(s< GO)return 66.67+(s-T)/(GO-T)*33.33; // 상승: T..GO  → 66.67..100
   return 100;}
 const nx=gPos(sc);
 const zoneDivs=Z.map(z=>'<div class="cg-zone" style="width:'+(z[4]-z[3]).toFixed(2)+'%;background:'+z[2]+'"></div>').join("");
 const ticks='<span style="left:33.33%">−.05</span><span style="left:50%">0</span><span style="left:66.67%">+.05</span>';
 const zlabs=Z.map(z=>'<span class="'+(z[0]===cur?"on":"")+'" style="left:'+((z[3]+z[4])/2).toFixed(2)+'%">'+z[1]+'</span>').join("");
 document.getElementById("cycGauge").innerHTML=
   '<div class="cg-lab">종합 강도 위치 — 임계 ±0.05 기준 국면 판정</div>'
   +'<div class="cg-wrap"><div class="cg-track">'+zoneDivs+'</div><div class="cg-needle" style="left:'+nx.toFixed(1)+'%"></div></div>'
   +'<div class="cg-ticks">'+ticks+'</div><div class="cg-zlab">'+zlabs+'</div>';
 // 현재 국면 지속 개월수 + 직전 국면(궤적)
 let hold=0,prev=cur;
 for(let mb=1;mb<=24;mb++){const ps=cycScore(mb);const st=stageOf(ps);if(st!==cur){prev=st;break;}hold=mb;}
 const trajLine=hold>0
   ?'현재 <b>'+cur+'</b> '+(hold+1)+'개월차'+(prev!==cur?'(직전 '+prev+'에서 전환)':'')+'. '
   :'현재 <b>'+cur+'</b>. ';
 document.getElementById("cycRead").innerHTML=trajLine+'국면 전환은 매수우위·전망지수가 기준 100을 위아래로 넘을 때 먼저 신호가 나와요.';}
function renderFoot(){const soon=PEND.filter(p=>p.st==="soon");
 let s='미니차트는 최근 1년(가로축 월 단위)';
 if(soon.length)s+=' · 연결예정 '+soon.length+'종('+soon.map(p=>p.lab).join("·")+')';
 document.getElementById("foot").innerHTML=s;}
renderCycle();renderPrice();renderCore();renderGroups();renderFoot();
(function(){function _fit(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;if(window.frameElement){window.frameElement.style.height=h+"px";window.frameElement.setAttribute("height",h);}}catch(e){}}window.addEventListener("load",_fit);setTimeout(_fit,150);setTimeout(_fit,600);setTimeout(_fit,1500);window.addEventListener("resize",_fit);try{new ResizeObserver(_fit).observe(document.body);}catch(e){}})();
</script></body></html>'''


def _indicators_v2_payload(data):
    """지표 시계열(list[{key,...,series}]) → 그룹·신호·해석 메타가 붙은 카드 리스트(live)와
    연결예정 슬롯(pend) 두 가지로 변환. 시계열 2개 미만은 제외."""
    by = {it.get("key"): it for it in (data or [])}
    ind = []
    for k in _INDV2_ORDER:
        it = by.get(k)
        if not it:
            continue
        series = [float(v) for v in (it.get("series") or []) if v is not None]
        if len(series) < 2:
            continue
        meta = _INDV2_DEF[k]
        ind.append({
            "k": k, "g": meta["g"], "lab": it.get("label", k),
            "sub": it.get("sub", ""), "cad": meta["cad"],
            "unit": it.get("unit", ""), "col": it.get("col", "#7E9A83"),
            "baseline": meta["baseline"], "inv": meta["inv"],
            "interp": meta["interp"], "base": round(series[-1], 2),
            "real": [round(v, 2) for v in series],
        })
    # pend 슬롯 = 연결예정(소스 자체 미연결). 라이브에 들어오면 자동으로 라이브 전환.
    live_keys = {d["k"] for d in ind}
    pend = [{**p, "st": "soon"} for p in _INDV2_PENDING if p["k"] not in live_keys]
    return ind, pend


def _price_block_payload(data):
    """지표 시계열 list에서 med/mean_seoul·sudo 4키를 묶어 '현재 매매가격' 블록용
    region 카드 리스트로 변환. 둘 다 없는 지역은 생략(빈 블록은 뷰에서 숨김)."""
    by = {it.get("key"): it for it in (data or [])}
    regions = [("seoul", "서울", "med_seoul", "mean_seoul"),
               ("sudo", "수도권", "med_sudo", "mean_sudo")]
    out = []
    for rk, label, mk_med, mk_mean in regions:
        med = [float(v) for v in ((by.get(mk_med) or {}).get("series") or [])
               if v is not None]
        mean = [float(v) for v in ((by.get(mk_mean) or {}).get("series") or [])
                if v is not None]
        if not med and not mean:
            continue
        out.append({"key": rk, "lab": label,
                    "med": [round(v, 2) for v in med],
                    "mean": [round(v, 2) for v in mean]})
    return out


def _indicator_chart_component(ind, pend, price, asof):
    import json as _json
    return (_INDV2_HTML
            .replace("__IND__", _json.dumps(ind, ensure_ascii=False))
            .replace("__PEND__", _json.dumps(pend, ensure_ascii=False))
            .replace("__PRICE__", _json.dumps(price, ensure_ascii=False))
            .replace("__G__", _json.dumps(_INDV2_GROUPS, ensure_ascii=False))
            .replace("__ASOF__", asof))


def _render_indicator_charts(data):
    """지표 탭 v2 — 사이클 위치 + 핵심 3 강조 카드 + 그룹별 컴팩트 행(미니차트 1년·월축).
    데이터는 엔진(매일 아침 수집) 가격지수 시계열을 그대로 쓰고, 미연결 항목은 '연결예정'으로 표시."""
    from datetime import date
    from math import ceil
    live = data is not _IND_SAMPLE
    ind, pend = _indicators_v2_payload(data)
    if not ind:
        st.caption("지표 데이터가 아직 없어요. 매일 아침 자동 수집 후 표시됩니다.")
        return
    asof = date.today().strftime("%Y-%m-%d")
    price = _price_block_payload(data)
    # 새 레이아웃 기준 높이 산정(클리핑 방지) — 헤더 + (가격블록) + 핵심 + 그룹 행들.
    _CORE = _INDV2_CORE
    core_n = len(_CORE)   # 핵심 카드(매수우위·매매전망)
    row_groups = {m["g"] for m in ind if m["k"] not in _CORE} | {p["g"] for p in pend}
    row_n = sum(1 for m in ind if m["k"] not in _CORE) + len(pend)
    height = (300                      # 사이클 헤더 + 판정 근거 + 강도 게이지
              + (60 + len(price) * 210 if price else 0)  # 현재 매매가격 블록(모바일 적층 여유)
              + 70                      # 핵심 섹션 라벨
              + ceil(max(core_n, 1) / 3) * 292   # 핵심 카드(미니차트+수위게이지)
              + 50                      # 그룹 섹션 라벨
              + len(row_groups) * 38    # 그룹 헤더들
              + row_n * 72              # 행들(스파크 시점축·Δ·수위게이지)
              + 80)                     # 푸터 여유
    components.html(_indicator_chart_component(ind, pend, price, asof),
                    height=height, scrolling=False)
    src = "KB 실데이터" if live else "샘플 · 아침 수집 후 실데이터로 교체"
    st.markdown(foot_row(
        src, "핵심(매수우위·매매전망) + 선행/동행/수급·심리 그룹 · "
             "미니차트 최근 1년(월 단위 축)"), unsafe_allow_html=True)


def _render_indicators(cards=None):
    if cards is None:
        cards = fetch_indicators()
    st.markdown(_market_phase(cards), unsafe_allow_html=True)
    html = ""
    for gtitle, gsub in _GROUP_ORDER:
        members = [c for c in cards if c["group"] == gtitle]
        if not members:
            continue
        html += f'<div class="re-grp">{gtitle}<span class="sub">{gsub}</span></div>'
        inner = ""
        for c in members:
            base_tag = (f'<span class="re-base">기준 {c["baseline"]}</span>'
                        if c.get("baseline") is not None else "")
            inner += (f'<div class="re-card"><div class="re-lab">{c["label"]}</div>'
                      f'<div class="re-val">{c["value"]}'
                      f'{_delta_html(c["series"], c.get("dunit", ""))}{base_tag}</div>'
                      f'{_spark_svg(c["series"], c["col"], c["kind"], c.get("baseline"))}'
                      f'<div class="re-note">{c["note"]}</div></div>')
        html += f'<div class="re-grid">{inner}</div>'
    st.markdown(html, unsafe_allow_html=True)
    st.caption("소스: KB · 부동산원 R-ONE · 통계청 KOSIS · 법원경매 · 국토부 · 한은 ECOS — "
               "매수우위·매매지수·전세가율(KB)·거래량(실거래)·미분양(KOSIS)·금리(ECOS) 실연결, "
               "나머지는 연결 예정(샘플). 항목별 갱신주기 상이. ▲빨강=상승 / ▼파랑=하락(직전값 대비)")


# ── 거래(특이거래) — 필터·정렬·지역 분류 ────────────────────────
_SEOUL_GU = {d["n"] for d in _GEO if d["sd"] == "seoul"}
_GG_SI = {d["n"] for d in _GEO if d["sd"] == "gg"}
_GANGNAM3 = {"강남구", "서초구", "송파구"}


def _region_of(gu):
    """단지 지역명(구/시)을 서울/경기로 분류. 못 찾으면 None."""
    if any(n in gu for n in _SEOUL_GU):
        return "seoul"
    if any(n in gu for n in _GG_SI):
        return "gg"
    return None


def _chg_abs(chg):
    """'+8.1%'·'-4.0%'·'+148%'·'×2.5'(거래량 배수) → 절대 크기(정렬·강조용)."""
    try:
        s = (str(chg).replace("%", "").replace("+", "")
             .replace("평소", "").replace("×", "").strip())
        return abs(float(s))
    except Exception:
        return 0.0


def _naver_land_url(query):
    """단지명(+동/구) → 네이버 통합검색(부동산 시세 카드 상단 노출). 퍼지라 약식명도 도달.
       (complexNo 딥링크 리졸브 전/실패 시의 폴백 · 키 불필요.)"""
    from urllib.parse import quote
    return "https://search.naver.com/search.naver?query=" + quote((query or "").strip())


def _naver_n(query):
    """단지명(+동/구) 옆 네이버 'N' 아이콘 링크 — 주도주 탭과 동일 스타일(.nv) · 통합검색."""
    import html as _html
    return (f'<a class="nv" href="{_html.escape(_naver_land_url(query))}" target="_blank" '
            f'rel="noopener" title="네이버 검색에서 보기">N</a>')


def _hot_spark_svg(vals, w=68, h=22):
    """단지 가격 추이 미니 스파크라인(P2) — ㎡당가 시퀀스 → polyline SVG.
    추세 방향색(상승 red·하락 blue·보합 sage). 점<2면 빈 문자열."""
    vals = [v for v in (vals or []) if isinstance(v, (int, float))]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = round(1 + i / (n - 1) * (w - 2), 1)
        y = round(h - 1 - (v - lo) / rng * (h - 3), 1)
        pts.append(f"{x},{y}")
    col = ("#B65F5A" if vals[-1] > vals[0]
           else "#5A7CA0" if vals[-1] < vals[0] else "#7E9A83")
    lx, ly = pts[-1].split(",")
    return (f'<span class="re-hc-spk"><span class="lab">추이</span>'
            f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<polyline fill="none" stroke="{col}" stroke-width="1.6" '
            f'stroke-linecap="round" stroke-linejoin="round" '
            f'points="{" ".join(pts)}"/>'
            f'<circle cx="{lx}" cy="{ly}" r="1.9" fill="{col}"/></svg></span>')


_WD_KR = ["월", "화", "수", "목", "금", "토", "일"]


def _anom_norm(rec):
    """특이거래 레코드를 15필드로 정규화(구 10~14필드 스냅샷 호환). 실패 시 None.
       (유형,배경,글자색,단지,지역,면적,가격,변동,거래유형,제외,거래일ISO|None,
        세대수|None, 빈도|None, 신호강도%|None, 평형별1년밴드|None)"""
    try:
        rec = list(rec)
    except TypeError:
        return None
    if len(rec) < 10:
        return None
    return (tuple(rec[:10])
            + (rec[10] if len(rec) >= 11 else None,)   # 거래일ISO
            + (rec[11] if len(rec) >= 12 else None,)    # 세대수
            + (rec[12] if len(rec) >= 13 else None,)    # 빈도(12개월 거래수)
            + (rec[13] if len(rec) >= 14 else None,)    # 신호강도%(sigstr)
            + (rec[14] if len(rec) >= 15 else None,))   # 평형별 1년 밴드(신고가)


def _anom_date(d):
    """'YYYY-MM-DD' → date. 실패 시 None."""
    from datetime import date as _date
    try:
        y, m, dd = str(d).split("-")[:3]
        return _date(int(y), int(m), int(dd))
    except Exception:
        return None


def _anom_daylabel(d):
    dt = _anom_date(d)
    return f"{dt.month:02d}.{dt.day:02d} ({_WD_KR[dt.weekday()]})" if dt else "날짜 미상"


_ANOM_PRESETS = {
    "느슨": {"freq": 5, "jump": 7.0, "margin": 0.3, "surge": 1.6, "days": 45},
    "표준": {"freq": 8, "jump": 10.0, "margin": 1.0, "surge": 2.0, "days": 30},
    "엄격": {"freq": 14, "jump": 13.0, "margin": 2.0, "surge": 3.0, "days": 21},
}


_CAPGAIN_HTML = r'''<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{--bg:#FCFCFA;--card:#fff;--ink:#34352f;--muted:#9a9b92;--line:#ECEDE7;
 --sage2:#7E9A83;--up:#B65F5A;--upT:#FBEEED;--dn:#5A7CA0;--dnT:#EDF1F5;--sum:#F6F7F2;--kf:'Pretendard',-apple-system,sans-serif;}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--kf);font-size:14px;-webkit-font-smoothing:antialiased}
.box{padding:2px 1px 8px}
.note{font-size:11px;color:var(--muted);line-height:1.55;margin:11px 2px 0}
.flat{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.fr{display:grid;grid-template-columns:26px 1fr auto;align-items:center;gap:11px;padding:11px 14px;border-bottom:1px solid var(--line)}
.fr:last-child{border-bottom:none}.fr:hover{background:var(--sum)}
.rank{font-size:15px;font-weight:800;color:var(--sage2);text-align:center}
.fr.top1 .rank{color:var(--up)}
.gu-badge{display:inline-block;font-size:10px;font-weight:800;color:var(--sage2);background:#EEF3EF;border-radius:5px;padding:1px 6px;margin-right:6px;vertical-align:middle}
.nm{font-size:13.5px;font-weight:700;color:var(--ink);line-height:1.25}
.nm small{display:block;font-size:11px;font-weight:600;color:var(--muted);margin-top:2px}
.yoy{text-align:right;white-space:nowrap}
.yoy b{font-size:17px;font-weight:800;letter-spacing:-.02em;border-radius:7px;padding:2px 8px}
.yoy b.up{color:var(--up);background:var(--upT)} .yoy b.dn{color:var(--dn);background:var(--dnT)}
.yoy small{display:block;font-size:10.5px;font-weight:600;color:var(--muted);margin-top:3px}
.empty{font-size:12px;color:var(--muted);padding:18px 6px}
.nv{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;flex:none;border-radius:4px;background:#03C75A;color:#fff;font-size:10px;font-weight:900;text-decoration:none;margin-left:5px;vertical-align:1px;line-height:1}.nv:hover{filter:brightness(.92)}
.mapln:hover{background:#EEF3EF;border-color:#A7BBA9}
</style></head><body><div class="box">
  <div class="flat" id="flat"></div>
  <div class="note">__NOTE__</div>
</div>
<script>
const GAIN=__GAIN__;
function mapLink(c){var q=encodeURIComponent(((c.dong||c.gu||"")+" "+c.apt).trim());
 return '<a class="nv" href="https://search.naver.com/search.naver?query='+q+'" target="_blank" rel="noopener" onclick="event.stopPropagation()" title="네이버 검색에서 보기">N</a>';}
function flat(){
 if(!GAIN||!GAIN.length){document.getElementById("flat").innerHTML='<div class="empty">데이터가 아직 없어요. 매일 아침 자동 수집 후 표시됩니다.</div>';return;}
 document.getElementById("flat").innerHTML=GAIN.map(function(c,i){
  var meta=c.units?(c.units.toLocaleString()+'세대 · '+c.dong):c.dong;
  var sub='현재 '+(c.peok||'—')+(c.cap?' · 시총 '+c.cap:'');
  var pos=c.val>=0;
  return '<div class="fr'+(i===0?' top1':'')+'"><div class="rank">'+(i+1)+'</div>'
   +'<div class="nm"><span class="gu-badge">'+c.gu+'</span>'+c.apt+'<small>'+meta+'</small></div>'
   +'<div class="yoy"><b class="'+(pos?'up':'dn')+'">'+(pos?'+':'')+c.val.toFixed(1)+'%</b><small>'+sub+'</small>'+mapLink(c)+'</div></div>';}).join("");}
flat();
(function(){function f(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;if(window.frameElement){window.frameElement.style.height=h+"px";window.frameElement.setAttribute("height",h);}}catch(e){}}window.addEventListener("load",f);setTimeout(f,150);setTimeout(f,600);setTimeout(f,1500);window.addEventListener("resize",f);try{new ResizeObserver(f).observe(document.body);}catch(e){}})();
</script></body></html>'''


def _render_cap_gainers(metric="ytd", top=10):
    """시총(=평단가) 상승률 보드 — metric='ytd'(작년말 대비) 또는 'mom'(3개월 모멘텀)."""
    import json as _json
    from datetime import date
    fld = "yoy" if metric == "ytd" else "mom"
    rows = []
    for c in (fetch_cap_gainers() or []):
        if not isinstance(c, dict):
            continue
        v = c.get(fld)
        gu = c.get("gu")
        apt = c.get("apt")
        if v is None or not gu or not apt:
            continue
        rows.append({"apt": apt, "gu": gu, "val": float(v),
                     "units": c.get("units"), "peok": c.get("price_eok") or "",
                     "cap": c.get("cap_fmt") or "", "dong": c.get("dong") or ""})
    if not rows:
        st.caption("데이터가 아직 없어요. 매일 아침 자동 수집 후 표시됩니다.")
        return
    rows.sort(key=lambda r: r["val"], reverse=True)
    rows = rows[:top]
    is_sample = fetch_cap_gainers() is _SAMPLE_CAPGAIN
    src = ("국토부 실거래 평단가" if not is_sample
           else "샘플 · 아침 수집 후 실데이터로 교체")
    if metric == "ytd":
        base = f"{date.today().year - 1}.12"
        note = (f'※ <b>작년말({base}) 대비</b> 면적정규화 평단가(㎡당가) 상승률. '
                f'세대수 불변이라 시총 상승률과 동일. 작년말·현재 모두 거래가 있는 단지만'
                f'(표본 부족·하락 단지 제외) · 매일 아침 갱신.')
        cap = "작년말 대비 평단가 상승률 · 시총 상승률과 동일(세대수 불변)"
    else:
        note = ('※ <b>3개월 전 대비</b> 평단가 모멘텀(최근 vs 3개월 전 ㎡당가). '
                'YTD가 누적 상승폭이라면 모멘텀은 <b>최근 가속/감속</b> 신호 · '
                '3개월 전·현재 모두 거래가 있는 단지만 · 매일 아침 갱신.')
        cap = "최근 3개월 모멘텀(3개월 전 대비 평단가) · 가속/감속 선행신호"
    height = 70 + len(rows) * 74 + 80
    html = (_CAPGAIN_HTML
            .replace("__GAIN__", _json.dumps(rows, ensure_ascii=False))
            .replace("__NOTE__", note))
    components.html(html, height=height, scrolling=False)
    st.markdown(foot_row(src, cap), unsafe_allow_html=True)


_CAPLEAD_HTML = r'''<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{--bg:#FCFCFA;--card:#fff;--ink:#34352f;--muted:#9a9b92;--line:#ECEDE7;--line2:#DEDED7;
 --sage2:#7E9A83;--up:#B65F5A;--sum:#F6F7F2;--kf:'Pretendard',-apple-system,sans-serif;}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--kf);font-size:14px;-webkit-font-smoothing:antialiased}
.box{padding:2px 1px 8px}
.sec{font-size:11.5px;font-weight:700;letter-spacing:.04em;color:var(--muted);text-transform:uppercase;margin:0 2px 11px;display:flex;align-items:center;gap:9px}
.sec::after{content:"";flex:1;height:1px;background:var(--line)}
.sec.mt{margin-top:22px}
.note{font-size:11px;color:var(--muted);line-height:1.55;margin:11px 2px 0}
.flat{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.fr{display:grid;grid-template-columns:26px 1fr auto;align-items:center;gap:11px;padding:11px 14px;border-bottom:1px solid var(--line)}
.fr:last-child{border-bottom:none}.fr:hover{background:var(--sum)}
.rank{font-size:15px;font-weight:800;color:var(--sage2);text-align:center}
.fr.top1 .rank,.rkrow.top1 .rank{color:var(--up)}
.gu-badge{display:inline-block;font-size:10px;font-weight:800;color:var(--sage2);background:#EEF3EF;border-radius:5px;padding:1px 6px;margin-right:6px;vertical-align:middle}
.nm{font-size:13.5px;font-weight:700;color:var(--ink);line-height:1.25}
.nm small{display:block;font-size:11px;font-weight:600;color:var(--muted);margin-top:2px}
.cap{text-align:right;white-space:nowrap}
.cap b{font-size:16px;font-weight:800;letter-spacing:-.02em;color:var(--ink)}
.cap small{display:block;font-size:10.5px;font-weight:600;color:var(--muted);margin-top:2px}
.picker{display:flex;align-items:center;gap:9px;margin-bottom:13px;flex-wrap:wrap}
.picker label{font-size:12px;font-weight:800;color:var(--sage2)}
.picker select{font-family:var(--kf);font-size:13px;font-weight:700;color:var(--ink);padding:7px 11px;border:1px solid var(--line2);border-radius:9px;background:#fff}
.sum-line{font-size:11.5px;color:var(--muted);font-weight:600}.sum-line b{color:var(--ink);font-weight:800}
.rk{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.rkrow{display:grid;grid-template-columns:30px 1fr auto;align-items:center;gap:12px;padding:13px 15px;border-bottom:1px solid var(--line)}
.rkrow:last-child{border-bottom:none}.rkrow:hover{background:var(--sum)}
.rkrow .rank{font-size:17px}.rkrow .nm{font-size:14px;font-weight:800}.rkrow .cap b{font-size:18px}
.jr-mini{display:flex;align-items:center;gap:8px;margin-top:6px}
.jr-mini .jg{flex:1;min-width:0;max-width:158px}
.jr-mini .jl{display:flex;justify-content:space-between;font-size:9.5px;font-weight:700;color:var(--muted);margin-bottom:3px}
.jr-mini .jl b{color:var(--sage2);font-weight:800}
.jr-mini .jb{height:6px;border-radius:3px;background:#EBECE6;overflow:hidden}
.jr-mini .jb i{display:block;height:100%;background:#A7BBA9}
.jr-mini .gp{font-size:10.5px;font-weight:700;color:#6f7068;white-space:nowrap}
.jr-mini .gp b{color:var(--ink);font-weight:800}
.empty{font-size:12px;color:var(--muted);padding:18px 6px}
.nv{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;flex:none;border-radius:4px;background:#03C75A;color:#fff;font-size:10px;font-weight:900;text-decoration:none;margin-left:5px;vertical-align:1px;line-height:1}.nv:hover{filter:brightness(.92)}
.mapln:hover{background:#EEF3EF;border-color:#A7BBA9}
</style></head><body><div class="box">
  <div class="sec">수도권 시가총액 TOP 10</div>
  <div class="flat" id="flat"></div>
  <div class="sec mt">구별 · 그룹별로 보기</div>
  <div class="picker"><label>지역</label><select id="sel" onchange="fill()"></select>
    <span class="sum-line" id="sumline"></span></div>
  <div class="rk" id="rk"></div>
  <div class="note">※ <b>시가총액(추정)</b> = 최근 실거래가(최근 거래 없으면 최근 대표가) × 세대수. <b>주요 단지 유니버스</b>(지역별 세대수 상위 단지)를 대상으로 집계해 조용한 대단지도 빠지지 않아요. 강남3구·마용성 같은 그룹은 합산 재정렬 TOP10, 개별 구는 TOP5 · 매일 아침 갱신.</div>
</div>
<script>
const CAP=__CAP__;
const GROUPS={"강남3구":["강남구","서초구","송파구"],"마용성":["마포구","용산구","성동구"],"노도강":["노원구","도봉구","강북구"]};
function capFmt(e){return e>=10000?(e/10000).toFixed(1)+"조":Math.round(e).toLocaleString()+"억";}
function mapLink(c){var q=encodeURIComponent(((c.dong||c.gu||"")+" "+c.apt).trim());
 return '<a class="nv" href="https://search.naver.com/search.naver?query='+q+'" target="_blank" rel="noopener" onclick="event.stopPropagation()" title="네이버 검색에서 보기">N</a>';}
function jrHtml(c){if(c.jr==null)return"";var w=Math.min(Math.round(c.jr),100);
 var gp=(c.gap!=null)?'<span class="gp">갭 <b>'+c.gap+'억</b></span>':'';
 return '<div class="jr-mini"><div class="jg"><div class="jl"><span>전세가율</span><b>'+Math.round(c.jr)+'%</b></div><div class="jb"><i style="width:'+w+'%"></i></div></div>'+gp+'</div>';}
const byGu={};CAP.forEach(function(c){(byGu[c.gu]=byGu[c.gu]||[]).push(c);});
const GUS=Object.keys(byGu).sort(function(a,b){
 return Math.max.apply(null,byGu[b].map(function(c){return c.cap;}))-Math.max.apply(null,byGu[a].map(function(c){return c.cap;}));});
function rowsRK(list,limit){return list.slice(0,limit).map(function(c,i){
 var badge=c._grp?'<span class="gu-badge">'+c.gu+'</span>':'';
 var meta=c.units.toLocaleString()+'세대 · '+(c.b?c.b+' · ':'')+c.dong;
 return '<div class="rkrow'+(i===0?' top1':'')+'"><div class="rank">'+(i+1)+'</div>'
  +'<div class="nm">'+badge+c.apt+'<small>'+meta+'</small>'+jrHtml(c)+'</div>'
  +'<div class="cap"><b>'+capFmt(c.cap)+'</b><small>최근 '+(c.peok||'—')+'</small>'+mapLink(c)+'</div></div>';}).join("");}
function fill(){var v=document.getElementById("sel").value,list,limit,label;
 if(GROUPS[v]){list=[];GROUPS[v].forEach(function(g){(byGu[g]||[]).forEach(function(c){var x=Object.assign({},c);x._grp=1;list.push(x);});});
  list.sort(function(a,b){return b.cap-a.cap;});limit=10;
  var su=list.slice(0,limit).reduce(function(s,c){return s+c.cap;},0);
  label='<b>'+v+'</b> 합산 · '+GROUPS[v].join("·")+' · 표시 시총합 <b>'+(su/10000).toFixed(1)+'조</b>';}
 else{list=(byGu[v]||[]).slice().sort(function(a,b){return b.cap-a.cap;});limit=5;label='<b>'+v+'</b> 시총 TOP5';}
 document.getElementById("rk").innerHTML=list.length?rowsRK(list,limit):'<div class="empty">해당 지역 유니버스 단지가 없어요.</div>';
 document.getElementById("sumline").innerHTML=label;}
function flat(){var all=CAP.slice().sort(function(a,b){return b.cap-a.cap;}).slice(0,10);
 document.getElementById("flat").innerHTML=all.length?all.map(function(c,i){
  return '<div class="fr'+(i===0?' top1':'')+'"><div class="rank">'+(i+1)+'</div>'
   +'<div class="nm"><span class="gu-badge">'+c.gu+'</span>'+c.apt+'<small style="font-weight:600;color:var(--muted)">'+c.units.toLocaleString()+'세대 · '+c.dong+'</small>'+jrHtml(c)+'</div>'
   +'<div class="cap"><b>'+capFmt(c.cap)+'</b><small>최근 '+(c.peok||'—')+'</small>'+mapLink(c)+'</div></div>';}).join("")
  :'<div class="empty">시총 데이터가 아직 없어요. 매일 아침 자동 수집 후 표시됩니다.</div>';}
(function(){var sel=document.getElementById("sel");
 var h='<optgroup label="그룹">'+Object.keys(GROUPS).map(function(g){return '<option>'+g+'</option>';}).join("")+'</optgroup>';
 h+='<optgroup label="자치구·시">'+GUS.map(function(g){return '<option>'+g+'</option>';}).join("")+'</optgroup>';
 sel.innerHTML=h;sel.value=GROUPS["강남3구"]?"강남3구":(GUS[0]||"");flat();fill();})();
(function(){function f(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;if(window.frameElement){window.frameElement.style.height=h+"px";window.frameElement.setAttribute("height",h);}}catch(e){}}window.addEventListener("load",f);setTimeout(f,150);setTimeout(f,600);setTimeout(f,1500);window.addEventListener("resize",f);try{new ResizeObserver(f).observe(document.body);}catch(e){}})();
</script></body></html>'''


def _render_cap_leaders():
    """구별·그룹별 시가총액 상위 단지 보드(수도권 TOP10 + 구/그룹 셀렉터)."""
    import json as _json
    rows = []
    for c in (fetch_cap_leaders() or []):
        if not isinstance(c, dict):
            continue
        cap = c.get("cap_eok")
        units = c.get("units")
        gu = c.get("gu")
        apt = c.get("apt")
        if not (cap and units and gu and apt):
            continue
        rows.append({"apt": apt, "gu": gu, "units": int(units),
                     "cap": int(cap), "peok": c.get("price_eok") or "",
                     "b": c.get("builder") or "", "dong": c.get("dong") or "",
                     "jr": c.get("jr"), "gap": c.get("gap_eok")})
    if not rows:
        st.caption("시총 데이터가 아직 없어요. 매일 아침 자동 수집 후 표시됩니다.")
        return
    n_gu = len(set(r["gu"] for r in rows))
    height = 110 + min(len(rows), 10) * 96 + 110 + 10 * 100 + 90
    html = _CAPLEAD_HTML.replace("__CAP__", _json.dumps(rows, ensure_ascii=False))
    components.html(html, height=height, scrolling=False)
    src = ("국토부 실거래 × 세대수" if fetch_cap_leaders() is not _SAMPLE_CAPLEAD
           else "샘플 · 아침 수집 후 실데이터로 교체")
    st.markdown(foot_row(
        src, f"시총=최근 실거래가(없으면 대표가)×세대수 · "
             f"주요 단지 유니버스 {n_gu}개 지역"), unsafe_allow_html=True)


def _render_hot_complexes():
    """주목 단지 보드 — 최근 거래 활발·상승(국토부 실거래) + 단지정보(세대수·시공사·소재지)
    + 면적별(59·84㎡) 최근 실거래가 + '네이버페이부동산' 링크."""
    hot = [h for h in (fetch_hot_complexes() or []) if isinstance(h, dict)]
    if not hot:
        return
    st.markdown('<div class="re-grp">주목 단지'
                '<span class="sub">주요 단지 중 가격·거래가 움직이는 대장주 · 국토부 실거래</span></div>',
                unsafe_allow_html=True)

    def _pp(lbl, val):
        if val:
            return f'<span class="re-hc-pp"><i>{lbl}</i>{val}</span>'
        return f'<span class="re-hc-pp dim"><i>{lbl}</i>–</span>'

    body = ""
    for i, h in enumerate(hot[:15], 1):
        sd = "서울" if h.get("sd") == "seoul" else "경기"
        chg = h.get("chg") or 0
        chg_cls = "up" if chg >= 0 else "dn"
        mult = h.get("vol_mult")
        if isinstance(mult, (int, float)):
            mcls = "up" if mult >= 1.5 else "dn" if mult < 0.8 else "mut"
            vol_s = f'<span class="{mcls}">평소 <b>×{mult}</b></span>'
        else:
            vol_s = '<span class="mut">신규 거래 집중</span>'
        apt = h.get("apt", "")
        addr = (h.get("addr") or f"{sd} {h.get('gu', '')}").strip()
        meta = [addr]
        u = h.get("units")
        if isinstance(u, (int, float)) and u:
            meta.append(f"{int(u):,}세대")
        if h.get("builder"):
            meta.append(str(h["builder"]))
        meta_s = " · ".join(m for m in meta if m)
        prices = _pp("59㎡", h.get("p59_eok")) + _pp("84㎡", h.get("p84_eok"))
        spark = _hot_spark_svg(h.get("spark"))
        jr = h.get("jr")
        if isinstance(jr, (int, float)):
            gap = h.get("gap_eok")
            gap_s = (f'<span class="re-hc-gap">갭 <b>{gap}억</b></span>'
                     if isinstance(gap, (int, float)) else "")
            jbox = (
                f'<div class="re-hc-jbox">'
                f'<div class="re-hc-jg"><div class="re-hc-jlab">'
                f'<span>전세가율</span><b>{int(round(jr))}%</b></div>'
                f'<div class="re-hc-jbar"><i style="width:{min(int(round(jr)), 100)}%">'
                f'</i></div></div>{gap_s}</div>')
        else:
            jbox = ""
        mq = (addr + " " + apt).strip() if addr else apt
        body += (
            f'<div class="re-hc"><span class="re-hc-rk">{i}</span>'
            f'<div class="re-hc-main">'
            f'<div class="re-hc-top"><span class="re-hc-nm">{apt}</span>'
            f'<span class="re-hc-chg {chg_cls}">{"+" if chg >= 0 else ""}{chg}%</span></div>'
            f'<div class="re-hc-meta">{meta_s}</div>'
            f'<div class="re-hc-stat">최근 {h.get("recent", 0)}건 · {vol_s} · '
            f'3개월 {h.get("freq", 0)}건</div>'
            f'<div class="re-hc-prices">{prices}{spark}</div>{jbox}</div>'
            f'{_naver_n(mq)}</div>')
    st.markdown(f'<div class="re-hcwrap">{body}</div>', unsafe_allow_html=True)
    st.markdown(foot_row(
        "국토부 실거래 · 직거래 제외",
        "주요 단지 유니버스 중 가격 모멘텀(3개월 등락)+거래 가속이 큰 대장주 순 · "
        "'평소 ×N'=최근 30일 거래밀도÷직전 60일 평균(기간 정규화) · "
        "59·84㎡는 각 면적대 최근 실거래가 · 전세가율=전세 ㎡당가÷매매 ㎡당가 · "
        "갭=(매매−전세)×대표면적 · 추이=대표면적대 ㎡당가 시퀀스 · "
        "N 아이콘(초록)으로 네이버 검색"), unsafe_allow_html=True)


def _hi_band_html(band, hi_area):
    """평형별 1년 밴드(list of {area,lo,hi,n}) → 칩 HTML(B안). 신고가 평형은 강조.
    밴드 데이터가 없으면 빈 문자열 반환 — 카드마다 결측 안내를 반복하지 않는다
    (수집이 쌓이면 자동으로 표시 · 결측 안내의 반복은 콘텐츠보다 소음이 커짐)."""
    if not band or not isinstance(band, list):
        return ""
    try:
        ha = int(float(str(hi_area).replace("㎡", "").strip()))
    except Exception:
        ha = None
    chips = ""
    for b in band:
        if not isinstance(b, dict):
            continue
        ar, lo, hi, n = b.get("area"), b.get("lo"), b.get("hi"), b.get("n")
        if ar is None or lo is None or hi is None:
            continue
        rng = f"{lo}억" if lo == hi else f"{lo}~{hi}억"
        n_s = f"<small>{int(n)}건</small>" if isinstance(n, (int, float)) and n else ""
        hl = " hl" if (ha is not None and int(ar) == ha) else ""
        chips += f'<span class="re-hi-chip{hl}">{int(ar)}㎡ <b>{rng}</b>{n_s}</span>'
    if not chips:
        return ""
    return ('<div class="re-hi-band">'
            '<div class="re-hi-bh">최근 1년 · 평형별 실거래가 밴드</div>'
            f'<div class="re-hi-chips">{chips}</div></div>')


def _render_anomalies():
    """특이거래 탭 — 신고가 전용. 각 신고가 단지의 평형별 최근 1년 실거래가 밴드 동반."""
    from datetime import date as _date
    today = _date.today()
    reg_f = st.segmented_control(
        "지역", ["수도권", "서울", "경기", "강남3구"],
        default="수도권", key="re_anom_region")
    sort_f = st.segmented_control(
        "정렬", ["최신순", "마진순", "금액순"],
        default="최신순", key="re_hi_sort")
    sens_f = st.segmented_control(
        "민감도", ["느슨", "표준", "엄격"], default="표준", key="re_anom_sens",
        help="소형단지(거래빈도) 컷·신고가 마진·표시기간을 한 번에 조절 — 너무 많/적으면 바꿔보세요")
    exclude_direct = st.checkbox("직거래(증여추정) 제외", value=True, key="re_excl_direct")
    P = _ANOM_PRESETS.get(sens_f or "표준", _ANOM_PRESETS["표준"])

    def _pass_region(gu):
        if reg_f == "서울":
            return _region_of(gu) == "seoul"
        if reg_f == "경기":
            return _region_of(gu) == "gg"
        if reg_f == "강남3구":
            return any(n in gu for n in _GANGNAM3)
        return True

    def _pass_preset(r):
        d, freq, sig = r[10], r[12], r[13]
        if isinstance(freq, (int, float)) and freq < P["freq"]:   # 소형/저유동 컷
            return False
        dt = _anom_date(d)                                        # 표시 기간 컷
        if dt and (today - dt).days > P["days"]:
            return False
        if isinstance(sig, (int, float)) and sig < P["margin"]:  # 신고가 마진 컷
            return False
        return True

    anoms = [na for na in (_anom_norm(r) for r in fetch_anomalies()) if na]
    rows = [r for r in anoms
            if r[0] == "신고가"
            and not (r[9] and exclude_direct)
            and _pass_region(r[4]) and _pass_preset(r)]

    if not rows:
        st.caption("조건에 맞는 신고가가 없어요. 민감도·지역을 바꿔보세요.")
        return

    def _price_won(p):
        try:
            s = str(p).replace(",", "").strip()
            return float(s.replace("억", "").strip()) if "억" in s else -1.0
        except Exception:
            return -1.0

    def _sig(r):
        return r[13] if isinstance(r[13], (int, float)) else 0.0

    if sort_f == "금액순":
        rows.sort(key=lambda r: _price_won(r[6]), reverse=True)
    elif sort_f == "마진순":
        rows.sort(key=_sig, reverse=True)
    else:   # 최신순
        rows.sort(key=lambda r: (r[10] is not None, r[10] or "", _sig(r)),
                  reverse=True)

    st.caption(f"신고가 {len(rows)}건 · 최근 {P['days']}일 · {reg_f} · "
               f"직거래 {'제외' if exclude_direct else '포함'}")

    grouped = (sort_f == "최신순")
    html = ""
    cur_day = None
    for (typ, bg, fg, apt, gu, area, price, chg, trade,
         excl, d, units, freq, sig, band) in rows:
        if grouped:
            dl = _anom_daylabel(d)
            if dl != cur_day:
                cur_day = dl
                html += f'<div class="re-daygroup">{dl}</div>'
        unit_s = (f" · {int(units):,}세대"
                  if isinstance(units, (int, float)) and units else "")
        freq_s = (f" · 1년 {int(freq)}건"
                  if isinstance(freq, (int, float)) and freq else "")
        trade_html = ('<span style="color:#A32D2D">직거래(증여추정·제외)</span>'
                      if trade == "직거래" else trade)
        date_inline = ("" if grouped or not _anom_date(d)
                       else f"{_anom_daylabel(d)} · ")
        margin_s = (f"신고 +{sig:.1f}%" if isinstance(sig, (int, float)) else "신고")
        apt_link = (f'<a href="{_naver_land_url(apt)}" target="_blank" '
                    f'rel="noopener">{apt}</a>')
        nmap = _naver_n(f"{gu} {apt}".strip())
        band_html = _hi_band_html(band, area)
        html += (
            f'<div class="re-hi{" excl" if excl else ""}">'
            f'<div class="re-hi-top">'
            f'<span class="re-bdg" style="background:{bg};color:{fg};margin-top:1px">{typ}</span>'
            f'<div style="flex:1;min-width:0"><div class="re-hi-nm">{apt_link}</div>'
            f'<div class="re-hi-sub">{gu} · {area}{unit_s}{freq_s} · '
            f'{date_inline}{trade_html}</div></div>'
            f'{nmap}'
            f'<div class="re-hi-price"><b>{price}</b>'
            f'<span class="tag">{margin_s}</span></div>'
            f'</div>{band_html}</div>')
    st.markdown(html, unsafe_allow_html=True)
    st.markdown(foot_row(
        "주요 단지 유니버스 · 국토부 실거래",
        "소형 노이즈 제외 · 신고가=최근 6개월 최고 초과(마진≥민감도) · "
        "밴드=해당 단지 각 평형의 최근 1년 실거래 최저~최고(직거래 제외 반영) · "
        "민감도로 양 조절 · 단지명·N 아이콘=네이버 검색"), unsafe_allow_html=True)


# ── 시장 요약 밴드(아파트 탭 상단 공통 1열) ─────────────────────────
#   특이거래 탭 기본(표준 민감도·수도권·직거래제외)과 동일 필터로 신고가/신저가
#   건수를 세어 '상승압력'을 만들고, 주목단지로 거래활발 단지수·평균 상승률을 보탠다.
#   엔진/스키마 무변경 — 기존 fetch_anomalies·fetch_hot_complexes 재집계.
_MARKET_BAND_HTML = r'''<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{--bg:#FCFCFA;--ink:#34352f;--muted:#9a9b92;--line:#E4E5DE;--track:#DCE2EA;
 --up:#B65F5A;--dn:#5A7CA0;--kf:'Pretendard',-apple-system,sans-serif;}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--kf);-webkit-font-smoothing:antialiased}
.band{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:16px 20px;display:flex;align-items:center;gap:24px;flex-wrap:wrap}
.hero{min-width:188px}
.cap{font-size:11px;font-weight:700;letter-spacing:.04em;color:var(--muted);text-transform:uppercase;margin-bottom:7px}
.dir{display:flex;align-items:baseline;gap:8px;margin-bottom:9px}
.dir .ar{font-size:15px}.dir .t{font-size:19px;font-weight:800;letter-spacing:-.02em;color:var(--ink)}
.dir .p{font-size:14px;font-weight:800}
.pbar{height:9px;border-radius:5px;background:var(--track);overflow:hidden}
.pbar .up{display:block;height:100%;background:var(--up)}
.nums{font-size:11px;font-weight:700;margin-top:6px;display:flex;justify-content:space-between}
.grid{flex:1;display:grid;grid-template-columns:repeat(4,1fr);gap:14px;min-width:258px}
.kl{font-size:11px;font-weight:700;color:var(--muted);margin-bottom:4px}
.kv{font-size:18px;font-weight:800;color:var(--ink);letter-spacing:-.02em}
.kv small{font-size:11px;font-weight:700;color:var(--muted);margin-left:2px}
</style></head><body>
<div class="band">
  <div class="hero">
    <div class="cap">오늘의 아파트 시장 · __DATE__</div>
    <div class="dir"><span class="ar" style="color:__DCOL__">__ARROW__</span><span class="t">__DLABEL__</span><span class="p" style="color:__DCOL__">__PCT__%</span></div>
    <div class="pbar"><span class="up" style="width:__PCT__%"></span></div>
    <div class="nums"><span style="color:var(--up)">신고가 __HI__</span><span style="color:var(--dn)">신저가 __LO__</span></div>
  </div>
  <div class="grid">
    <div><div class="kl">신고가</div><div class="kv" style="color:var(--up)">__HI__<small>건</small></div></div>
    <div><div class="kl">신저가</div><div class="kv" style="color:var(--dn)">__LO__<small>건</small></div></div>
    <div><div class="kl">거래활발</div><div class="kv">__ACT__<small>단지</small></div></div>
    <div><div class="kl">평균 상승률</div><div class="kv" style="color:__GCOL__">__GAIN__</div></div>
  </div>
</div>
<script>
(function(){function _fit(){try{var h=Math.ceil(document.body.getBoundingClientRect().height)+2;if(window.frameElement){window.frameElement.style.height=h+"px";window.frameElement.setAttribute("height",h);}}catch(e){}}window.addEventListener("load",_fit);setTimeout(_fit,150);setTimeout(_fit,600);setTimeout(_fit,1500);window.addEventListener("resize",_fit);try{new ResizeObserver(_fit).observe(document.body);}catch(e){}})();
</script>
</body></html>'''


def _summary_core(anoms_raw, hot_raw, asof_dt):
    """스냅샷 원천(anomalies, metrics._hot)에서 5개 지표 집계 — 특이거래 표준 프리셋
    (직거래제외)과 일치하는 신고가/신저가 건수 + 주목단지 거래활발 단지수·평균 상승률.
    asof_dt=표시 기간(P['days']) 필터 기준일. 반환 {hi,lo,act,avg,latest} 또는 None(표본 0)."""
    P = _ANOM_PRESETS["표준"]

    def _pass(r):
        typ, d, freq, sig = r[0], r[10], r[12], r[13]
        if isinstance(freq, (int, float)) and freq < P["freq"]:
            return False
        dt = _anom_date(d)
        if dt and (asof_dt - dt).days > P["days"]:
            return False
        if isinstance(sig, (int, float)):
            if typ in ("급등", "급락") and sig < P["jump"]:
                return False
            if typ in ("신고가", "신저가") and sig < P["margin"]:
                return False
            if typ == "거래량 급증" and sig < P["surge"]:
                return False
        return True

    normed = [na for na in (_anom_norm(r) for r in (anoms_raw or [])) if na]
    pool = [r for r in normed if not r[9] and _pass(r)]
    hi = sum(1 for r in pool if r[0] == "신고가")
    lo = sum(1 for r in pool if r[0] == "신저가")
    _tx = [dt for dt in (_anom_date(r[10]) for r in pool) if dt]
    latest = max(_tx) if _tx else None
    hot = [h for h in (hot_raw or []) if isinstance(h, dict)]
    act = len(hot)
    chgs = [h.get("chg") for h in hot if isinstance(h.get("chg"), (int, float))]
    avg = round(sum(chgs) / len(chgs), 1) if chgs else None
    if hi + lo == 0 and act == 0:
        return None
    return {"hi": hi, "lo": lo, "act": act, "avg": avg, "latest": latest}


def _market_summary():
    """오늘의 요약 밴드 집계(최신 스냅샷 기준). 반환 dict 또는 None(표본 0)."""
    from datetime import date as _date
    today = _date.today()
    s = _summary_core(fetch_anomalies(), fetch_hot_complexes(), today)
    if not s:
        return None
    s["today"] = today
    return s


def _render_market_band():
    """'아파트' 탭 상단 시장 요약 밴드(헤드라인 방향 배지) — 서브탭 위 공통 1열."""
    s = _market_summary()
    if not s:
        return
    hi, lo, tot = s["hi"], s["lo"], s["hi"] + s["lo"]
    pct = round(hi / tot * 100) if tot else 50
    if pct >= 60:
        dlabel, arrow, dcol = "상승 우세", "▲", "#B65F5A"
    elif pct <= 40:
        dlabel, arrow, dcol = "하락 우세", "▼", "#5A7CA0"
    else:
        dlabel, arrow, dcol = "혼조", "◆", "#7E9A83"
    avg = s["avg"]
    if avg is None:
        gain, gcol = "–", "#9a9b92"
    else:
        gcol = "#B65F5A" if avg >= 0 else "#5A7CA0"
        gain = f'{"+" if avg >= 0 else ""}{avg}<small>%</small>'
    _ref = s.get("latest")
    datestr = (f'{_ref.month}.{_ref.day} 최신거래 기준' if _ref
               else f'{s["today"].month}.{s["today"].day} 기준')
    html = (_MARKET_BAND_HTML
            .replace("__DATE__", datestr)
            .replace("__DLABEL__", dlabel)
            .replace("__ARROW__", arrow)
            .replace("__DCOL__", dcol)
            .replace("__PCT__", str(pct))
            .replace("__HI__", str(hi))
            .replace("__LO__", str(lo))
            .replace("__ACT__", str(s["act"]))
            .replace("__GCOL__", gcol)
            .replace("__GAIN__", gain))
    components.html(html, height=210, scrolling=False)
    st.markdown(foot_row(
        "특이거래 탭과 동일 집계",
        "상승압력=신고가÷(신고가+신저가) · 표준 민감도·직거래 제외 · "
        "거래활발=주목단지 랭킹 단지수 · 평균 상승률=주목단지 평균"), unsafe_allow_html=True)


def _wk_spark(vals, color, w=132, h=30, pad=3):
    """주간 지표 시계열 → 폭 채움 스파크라인 SVG(A안). 점<2면 '–'."""
    vv = [v for v in vals if isinstance(v, (int, float))]
    if len(vv) < 2:
        return '<span class="wk-spark-na">–</span>'
    lo, hi = min(vv), max(vv)
    rng = (hi - lo) or 1
    n = len(vv)
    pts = []
    for i, v in enumerate(vv):
        x = pad + i / (n - 1) * (w - 2 * pad)
        y = h - pad - (v - lo) / rng * (h - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    return (f'<svg class="wk-spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" '
            f'width="100%" height="{h}"><polyline fill="none" stroke="{color}" '
            f'stroke-width="1.6" vector-effect="non-scaling-stroke" '
            f'stroke-linecap="round" stroke-linejoin="round" '
            f'points="{" ".join(pts)}"/></svg>')


def _render_market_week():
    """주간(최근 7일) 아파트 시장 — 지표별 스파크라인(A안). 일별 스냅샷을 날짜별로 재집계.
    이력이 7일 미만이면 있는 만큼만 표시. 스냅샷 미설정/부재면 안내."""
    from datetime import date as _date
    rows = _load_recent_re_snapshots(7)
    if not rows:
        st.caption("주간 데이터가 아직 없어요. 매일 아침 자동 수집분이 하루씩 쌓이면 채워집니다.")
        return

    series = []   # [(date, summary)] 오래된→최신
    for row in reversed(rows):
        ad = str(row.get("asof_date") or "")[:10]
        try:
            y, m, d = ad.split("-")
            asof_dt = _date(int(y), int(m), int(d))
        except Exception:
            continue
        hot = (row.get("metrics") or {}).get("_hot")
        s = _summary_core(row.get("anomalies"), hot, asof_dt)
        if s is None:
            s = {"hi": 0, "lo": 0, "act": 0, "avg": None}
        tot = s["hi"] + s["lo"]
        s["up"] = round(s["hi"] / tot * 100) if tot else 50
        series.append((asof_dt, s))
    if len(series) < 1:
        st.caption("주간 데이터가 아직 없어요. 매일 아침 수집분이 쌓이면 채워집니다.")
        return

    ups = [s["up"] for _, s in series]
    his = [s["hi"] for _, s in series]
    los = [s["lo"] for _, s in series]
    acts = [s["act"] for _, s in series]
    avgs = [(s["avg"] if s["avg"] is not None else 0.0) for _, s in series]
    d0, d1 = series[0][0], series[-1][0]

    def _delta(vals, dec=0):
        d = vals[-1] - vals[0]
        d = round(d, dec) if dec else int(round(d))
        return d

    def _row(name, vals, last_str, delta, color_cls, spark_col, hero=False):
        if delta > 0:
            dcls, dsym, dv = "wk-up", "▲", f"+{delta}"
        elif delta < 0:
            dcls, dsym, dv = "wk-dn", "▼", f"{delta}"
        else:
            dcls, dsym, dv = "wk-mut", "–", "0"
        return (
            f'<div class="wk-row{" hero" if hero else ""}"><span class="k">{name}</span>'
            f'{_wk_spark(vals, spark_col)}'
            f'<span class="r"><b class="{color_cls}">{last_str}</b>'
            f'<span class="d {dcls}">{dsym} {dv}</span></span></div>')

    up_last = ups[-1]
    up_cls = "wk-up" if up_last >= 60 else ("wk-dn" if up_last <= 40 else "wk-sg")
    up_col = "#B65F5A" if up_last >= 60 else ("#5A7CA0" if up_last <= 40 else "#7E9A83")
    avg_last = avgs[-1]
    avg_cls = "wk-up" if avg_last >= 0 else "wk-dn"
    avg_str = f'{"+" if avg_last >= 0 else ""}{round(avg_last, 1)}%'

    body = (
        _row("상승 우세", ups, f"{up_last}%", _delta(ups), up_cls, up_col, hero=True)
        + _row("신고가", his, f"{his[-1]}건", _delta(his), "wk-up", "#B65F5A")
        + _row("신저가", los, f"{los[-1]}건", _delta(los), "wk-dn", "#5A7CA0")
        + _row("거래활발", acts, f"{acts[-1]}단지", _delta(acts), "wk-sg", "#7E9A83")
        + _row("평균 상승률", avgs, avg_str, _delta(avgs, 1), avg_cls, "#B65F5A"))
    st.markdown(f'<div class="wk-wrap">{body}</div>', unsafe_allow_html=True)
    st.markdown(foot_row(
        f"주간 {d0.month}.{d0.day}→{d1.month}.{d1.day} · {len(series)}일",
        "각 지표를 일별 스냅샷에서 재집계(표준 민감도·직거래 제외) · "
        "주간Δ=마지막−처음 · 상승우세=신고가÷(신고가+신저가)"), unsafe_allow_html=True)


# ── 메인 ────────────────────────────────────────────────────────
def _render_subscriptions():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    WD = ["월", "화", "수", "목", "금", "토", "일"]

    region = st.segmented_control(
        "지역", ["수도권", "서울", "경기"], default="수도권",
        key="re_sub_region", label_visibility="collapsed")
    rmap = {"서울": "seoul", "경기": "gg"}
    subs = fetch_subscriptions()
    live = subs is not _SAMPLE_SUBS

    items = []
    for row in subs:
        try:
            nm, gu, addr, typ, nse, s, e, mv, sd = row[:9]
        except (ValueError, TypeError):
            continue
        url = row[9] if len(row) > 9 else ""   # 10-튜플=청약홈 공고, 9-튜플=폴백
        if region in rmap and sd != rmap[region]:
            continue
        status, order = _sub_status(s, e)
        sdt, edt = _sub_window(s, e)
        items.append({"order": order, "s": s, "e": e, "sdt": sdt, "edt": edt,
                      "status": status, "dday": _sub_dday(sdt, edt, status),
                      "nm": nm, "gu": gu, "addr": addr, "typ": typ,
                      "nse": nse, "mv": mv, "sd": sd,
                      "url": (url or _APPLYHOME_LIST)})
    items.sort(key=lambda x: (x["order"], x["s"]))
    if not items:
        st.caption("해당 지역 분양 단지가 없어요.")
        return

    def _units(nse):
        try:
            return f"{int(nse):,}세대"
        except (ValueError, TypeError):
            return "-세대"

    # ── 청약 임박 하이라이트 (진행 중 + 7일 내 시작) ──
    def _urgent(it):
        if it["status"] == "분양중":
            return True
        if it["status"] == "예정" and it["sdt"] is not None:
            return 0 <= (it["sdt"] - today).days <= 7
        return False
    hot = [it for it in items if _urgent(it)]
    hot.sort(key=lambda it: (0 if it["status"] == "분양중" else 1, it["sdt"] or today))
    if hot:
        cards = ""
        for it in hot[:3]:
            reg_kr = "서울" if it["sd"] == "seoul" else "경기"
            nmap = _naver_n((it["addr"] + " " + it["nm"]).strip())
            cards += (f'<div class="re-hl-card">'
                      f'<span class="re-hl-dday">{it["dday"]}</span>'
                      f'<div class="re-hl-nm">{it["nm"]}</div>'
                      f'<div class="re-hl-meta">{reg_kr} {it["gu"]} · {it["typ"]} · {_units(it["nse"])}</div>'
                      f'<div class="re-hl-when">청약 {it["s"]}~{it["e"]} · 입주 {it["mv"]}</div>'
                      f'<div class="re-hl-acts">'
                      f'<a class="re-go-btn gold" href="{it["url"]}" target="_blank" rel="noopener">공고 ↗</a>'
                      f'{nmap}'
                      f'</div></div>')
        st.markdown('<div class="re-hl-sec">청약 임박 <span>진행 중 · 7일 내 시작</span></div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="re-hl">{cards}</div>', unsafe_allow_html=True)

    # ── 향후 2주 청약 일정 타임라인 (시작/마감 이벤트일) ──
    ev = {}
    for it in items:
        if it["sdt"] is None:
            continue
        for d, kind in ((it["sdt"], "s"), (it["edt"], "e")):
            if today <= d <= today + timedelta(days=13):
                ev.setdefault(d, []).append((it["nm"], kind))
    if ev:
        cols = ""
        for d in sorted(ev.keys())[:8]:
            evs = ev[d]
            kind = "s" if any(k == "s" for _, k in evs) else "e"
            more = f" 외 {len(evs)-1}" if len(evs) > 1 else ""
            tag = "시작" if kind == "s" else "마감"
            cols += (f'<div class="re-tl-col"><div class="re-tl-d">{WD[d.weekday()]} {d.day}</div>'
                     f'<div class="re-tl-dot {kind}"></div>'
                     f'<div class="re-tl-c">{evs[0][0]}{more}<br>{tag}</div></div>')
        st.markdown('<div class="re-hl-sec">향후 2주 청약 일정 '
                    '<span>시작 ●초록 · 마감 ●빨강</span></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="re-tl">{cols}</div>', unsafe_allow_html=True)

    # ── 전체 리스트 (D-day 배지) ──
    st.markdown('<div class="re-hl-sec">전체 분양 단지</div>', unsafe_allow_html=True)
    bdg = {"분양중": ("#FCEBEB", "#A32D2D"), "예정": ("#EAF1EA", "#3F6F49"),
           "마감": ("#F0F1EC", "#8A8C82")}
    html = ""
    for it in items:
        bg, fg = bdg[it["status"]]
        reg_kr = "서울" if it["sd"] == "seoul" else "경기"
        nmap = _naver_n((it["addr"] + " " + it["nm"]).strip())
        html += (f'<div class="re-sub-card">'
                 f'<span class="re-sub-bdg" style="background:{bg};color:{fg}">{it["dday"]}</span>'
                 f'<div style="flex:1;min-width:0"><div class="re-sub-nm">{it["nm"]}</div>'
                 f'<div class="re-sub-meta">{reg_kr} {it["gu"]} · {it["typ"]} · '
                 f'{_units(it["nse"])} · {it["addr"]}</div>'
                 f'<div class="re-sub-when">청약 {it["s"]}~{it["e"]} · 입주 {it["mv"]}</div></div>'
                 f'<div class="re-sub-acts">'
                 f'<a class="re-go-btn" href="{it["url"]}" target="_blank" rel="noopener">공고 ↗</a>'
                 f'{nmap}'
                 f'</div></div>')
    st.markdown(html, unsafe_allow_html=True)
    if live:
        st.markdown(foot_row(
            "청약홈 · data.go.kr",
            "'공고 ↗'는 청약홈 해당 공고, 초록 N은 네이버 검색으로 이동 · "
            "D-day는 청약 시작일(예정)·마감일(진행 중) 기준 자동 계산 · "
            "진행/임박 우선"), unsafe_allow_html=True)
    else:
        st.markdown(foot_row(
            "청약홈 · 샘플",
            "'갱신'을 누르면 실데이터(청약홈 분양정보 활용신청 필요) · "
            "'공고 ↗'는 청약홈(샘플은 공고 목록), 초록 N은 네이버 검색으로 이동 · "
            "D-day는 청약 시작·마감일 기준 자동 계산"), unsafe_allow_html=True)


def _run_collection():
    """뷰어 '최신 데이터 불러오기' — 라이브 API를 호출하지 않고 DB 스냅샷만 다시 읽는다.

    KB(data-api.kbland.kr)는 Streamlit Cloud IP에서 차단/타임아웃되고, 국토부 대량 호출도
    뷰어에서는 불안정하다(엔진-우선 원칙). 그래서 실제 수집은 매일 아침 GitHub Actions가
    수행해 Supabase(realestate_snapshots)에 채우고, 뷰어는 그 최신 행을 읽기만 한다.
    이 함수는 스냅샷 캐시를 비워 '방금 아침/수동 워크플로가 쓴 최신본'을 즉시 반영한다.
    (예외를 던지지 않는다 — 에러 배너 대신 항상 DB/샘플을 보여준다.)"""
    try:
        _load_re_snapshot.clear()      # 스냅샷 캐시 무효화 → 다음 읽기에서 DB 최신본 로드
    except Exception:
        pass
    # 직전 세션에 남아 있던 라이브 갱신값을 지워 DB 스냅샷이 그대로 보이게 한다.
    for k in ("re_metrics", "re_anoms", "re_subs", "re_indseries", "re_asof"):
        st.session_state.pop(k, None)


def _re_authed():
    """소유자 인증 여부만 판단 — 위젯을 그리지 않는다(여러 탭에서 안전하게 호출).
       APP_PASSWORD 미설정이면 누구나 가능. 리포트 잠금(gen_authed)을 공유한다."""
    try:
        pw = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        pw = ""
    return (not pw) or bool(st.session_state.get("gen_authed"))


def _re_render_lock_gate():
    """비밀번호 잠금 UI를 '한 번만' 렌더(지도 탭 전용). 이미 인증됐으면 아무것도 안 그린다.
       위젯(key=re_pw/re_unlock)이 여러 탭에서 중복 생성되던 DuplicateElementKey를 방지."""
    if _re_authed():
        return
    try:
        pw = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        pw = ""
    with st.expander("🔒 실거래 갱신은 소유자 전용이에요", expanded=False):
        st.caption("둘러보기는 자유롭고, 갱신(공공API 대량 호출)만 소유자 비밀번호가 필요해요.")
        p = st.text_input("비밀번호", type="password", key="re_pw")
        if st.button("잠금 해제", key="re_unlock"):
            if p == pw:
                st.session_state["gen_authed"] = True
                st.success("잠금 해제됐어요.")
                st.rerun()
            else:
                st.error("비밀번호가 일치하지 않아요.")


def _re_collect_asof():
    """부동산 스냅샷 수집 기준시각(asof · KST 문자열). 세션 → 스냅샷. 없으면 None."""
    a = st.session_state.get("re_asof")
    if not a:
        snap = _load_re_snapshot()
        a = (snap or {}).get("asof") if snap else None
    return a


def _render_collect_controls():
    """지도 탭 상단 컨트롤 — 데이터 기준 캡션 + 갱신/진단 버튼 + 수집·진단 처리.
       (증시 '새로고침'과 같은 위치: 서브탭 제목 바로 아래.)"""
    asof = _re_collect_asof()
    if asof:
        st.caption(f"수도권·광역시 아파트 · 매매·전세=KB 월간 가격지수, 거래=주간 실거래 · 기준 {asof} KST · 매일 아침 자동 갱신 · 최근·다음 시각은 하단 🕐 자동 갱신 현황")
    else:
        st.caption("수도권 아파트 · 현재 샘플 — 매일 아침 자동 수집(KB 가격지수·실거래) 후 "
                   "실데이터로 채워집니다.")

    _re_render_lock_gate()
    authed = _re_authed()
    col_a, col_b = st.columns([3, 1])
    with col_a:
        do_collect = st.button(
            "🔄 최신 데이터 불러오기", disabled=not authed,
            help="매일 아침 GitHub Actions가 KB·국토부 데이터를 수집해 DB에 저장합니다. "
                 "이 버튼은 그 최신본을 즉시 다시 불러옵니다(라이브 API 호출 없음).",
            use_container_width=True)
    with col_b:
        do_diag = st.button(
            "🔍 연결 진단", help="단 1회 시험 호출로 키·네트워크 상태만 점검",
            use_container_width=True)

    # 연결 진단: 600콜 안 돌리고 강남구 1콜만 던져 원인을 바로 표시
    if do_diag:
        from engine.realestate_collect import diagnose
        with st.spinner("data.go.kr 연결 점검 중..."):
            try:
                status, msg = diagnose()
            except Exception as e:
                status, msg = "API_ERROR", str(e)
        if status in ("OK", "OK_EMPTY"):
            st.success(f"[{status}] {msg}")
        else:
            st.error(f"[{status}] {msg}")

    if do_collect:
        with st.spinner("DB에서 최신본 불러오는 중..."):
            _run_collection()
        st.success("최신 데이터를 불러왔어요.")
        st.rerun()


def render_realestate():
    """부동산 탭 본문 — 지도 / 지표 / 거래 / 분양 서브탭.

    증시 탭과 동일 구조로 통일: 서브탭을 먼저 두고, 각 서브탭 안에서
    [액센트 바(.accent-bar) + 제목(st.title) + 캡션/컨트롤]로 연다.
    (.accent-bar·h1 스타일은 app.py 전역 CSS를 그대로 사용해 증시와 픽셀 일치.)
    갱신/진단은 주 화면인 '지도' 탭 안에 위치하고, 나머지 탭은 같은 세션/스냅샷을 읽는다.
    """
    # ── lazy 서브탭: 선택된 탭만 실제 실행(매 렌더마다 5개 탭이 다 도는 부담 제거) ──
    #   부동산은 최대 규모 모듈이라 효과가 크다. 증시 상단탭과 동일한 st.segmented_control.
    #   단, _RE_CSS(부동산 전용 스타일)는 예전엔 항상 실행되던 '사이클' 탭에서만 주입됐으므로,
    #   어느 탭으로 바로 진입해도 스타일이 붙도록 각 분기에서 주입한다(한 렌더에 한 분기만
    #   실행 → 중복 없음, accent-bar와 한 블록으로 합쳐 세로 간격도 유지).
    _re_maintab = st.segmented_control(
        "부동산 탭", ["사이클", "지도", "실거래", "분양", "테마"], default="사이클",
        key="re_maintab", label_visibility="collapsed",
    ) or "사이클"   # 선택 해제(None) 시 기본값으로 폴백

    if _re_maintab == "사이클":
        st.markdown(_RE_CSS + '<div class="accent-bar"></div>',
                    unsafe_allow_html=True)
        st.title("부동산 시장 지표")
        _cyc_asof = _re_collect_asof()
        if _cyc_asof:
            st.caption("부동산 사이클·선행지표 — 매수우위·매매전망·선도50·전세수급"
                       f"(KB 주간·월간) · 기준 {_cyc_asof} KST · "
                       "항목별 갱신주기 상이 · 매일 아침 자동 갱신")
        else:
            st.caption("부동산 사이클·선행지표 — KB 주간·월간 지수 기반 · "
                       "현재 샘플(아침 자동 수집 후 실데이터로 채워집니다)")
        _render_indicator_charts(_resolved_indicator_series())

    elif _re_maintab == "지도":
        st.markdown(_RE_CSS + '<div class="accent-bar"></div>', unsafe_allow_html=True)
        st.title("가격지도")
        _render_collect_controls()
        _render_watchlist_band()
        _render_streak_section()
        _render_map()

    elif _re_maintab == "실거래":
        st.markdown(_RE_CSS + '<div class="accent-bar"></div>', unsafe_allow_html=True)
        st.title("아파트 실거래")
        st.caption("아파트 단지·실거래 종합 — 시장 방향·특이거래·시총·주목단지 · "
                   "국토부 실거래 기준 · 직거래 기본 제외")
        _band_view = st.segmented_control(
            "기간", ["오늘", "주간"], default="오늘", key="re_band_view",
            label_visibility="collapsed")
        if _band_view == "주간":
            _render_market_week()
        else:
            _render_market_band()
        st_anom, st_cap, st_hot = st.tabs(["특이거래", "시총", "주목 단지"])
        with st_anom:
            st.markdown('<div class="re-grp">특이거래'
                        '<span class="sub">신고가 · 평형별 최근 1년 실거래가 밴드</span></div>',
                        unsafe_allow_html=True)
            _render_anomalies()
        with st_cap:
            cap_view = st.segmented_control(
                "보기", ["시가총액", "상승률", "모멘텀"], default="시가총액",
                key="re_cap_view", label_visibility="collapsed")
            if cap_view == "상승률":
                st.markdown('<div class="re-grp">작년말 대비 시총 상승률'
                            '<span class="sub">전년 12월 대비 평단가(YTD 누적) · 상승률 = 시총 상승률</span></div>',
                            unsafe_allow_html=True)
                _render_cap_gainers("ytd")
            elif cap_view == "모멘텀":
                st.markdown('<div class="re-grp">최근 3개월 모멘텀'
                            '<span class="sub">3개월 전 대비 평단가 · 최근 가속/감속 선행신호</span></div>',
                            unsafe_allow_html=True)
                _render_cap_gainers("mom")
            else:
                st.markdown('<div class="re-grp">구별 시가총액 상위 단지'
                            '<span class="sub">최근 실거래가 × 세대수 · 강남3구 등 그룹 합산</span></div>',
                            unsafe_allow_html=True)
                _render_cap_leaders()
        with st_hot:
            _render_hot_complexes()

    elif _re_maintab == "분양":
        st.markdown(_RE_CSS + '<div class="accent-bar"></div>', unsafe_allow_html=True)
        st.title("분양 단지")
        st.caption("한국부동산원 청약홈 분양정보 · 청약 임박·진행 우선 · 매일 아침 자동 갱신 · 최근·다음 시각은 하단 🕐 자동 갱신 현황")
        if _re_authed():
            if st.button(
                    "🔄 최신 분양정보 불러오기", key="re_sub_refresh",
                    help="매일 아침 GitHub Actions가 청약홈 분양정보를 수집해 DB에 저장합니다. "
                         "이 버튼은 그 최신본을 즉시 다시 불러옵니다.",
                    use_container_width=True):
                with st.spinner("DB에서 최신 분양정보 불러오는 중..."):
                    _run_collection()
                st.success("최신 분양정보를 불러왔어요.")
                st.rerun()
        _render_subscriptions()

    else:  # 테마
        # _RE_CSS를 먼저 주입(이 탭으로 바로 진입해도 부동산 스타일 유지).
        # 키워드 뷰어가 자체적으로 accent-bar + 제목을 그린다(증시 키워드 탭과 동일).
        st.markdown(_RE_CSS, unsafe_allow_html=True)
        from modules.realestate_keywords_view import render_realestate_keywords
        render_realestate_keywords()
