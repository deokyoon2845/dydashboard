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
        out.append({**d, **{k: m[k] for k in ("mm", "js", "v", "vc", "jr") if k in m}})
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
        {"group": "선행·심리", "label": "경매 낙찰가율(서울)", "value": "94.2%", "kind": "line",
         "col": "#B65F5A", "series": [86, 88, 87, 90, 92, 93, 94.2],
         "note": "법원경매 월간 · 선행지표", "dunit": "%p", "baseline": None},
        mi_card,
        jr_card,
        {"group": "공급·펀더멘털", "label": "입주물량(수도권)", "value": "8.4천호", "kind": "bar",
         "col": "#9a9b92", "series": [6.1, 9.8, 7, 11.5, 5.2, 4.8, 8.4],
         "note": "국토부/민간 월별", "dunit": "천호", "baseline": None},
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
    "unsold":  ("미분양", "month", 100, "%"),
    "rate":    ("주담대금리", "month", 100, "p"),
}
# baseline(중립선 100)이 의미 있는 심리지표만 — 매수우위·전세수급·매매전망
_IND_BASELINE = {"buy": 100, "jsup": 100, "outlook": 100}

# ── 지표 탭 v2: 의미 레이어(사이클·그룹·신호·해석) 메타 ───────────────
#   g=그룹 · baseline=중립선(없으면 None) · inv=역행(낮을수록 시장 긍정) · interp=한 줄 해석
_INDV2_GROUPS = {
    "lead":   {"name": "선행지표", "desc": "먼저 움직인다 — 방향 신호"},
    "coin":   {"name": "동행지표", "desc": "지금 가격·거래"},
    "supply": {"name": "수급·심리", "desc": "전세·갭·기대"},
    "fund":   {"name": "펀더멘털·금융", "desc": "재고·공급·구매력 (역행)"},
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
    "volume":   {"g": "coin", "cad": "month", "baseline": None, "inv": False,
                 "interp": "월별 아파트 매매 건수. 시장의 체온—거래가 살아나면 추세가 강해짐."},
    "jsup":     {"g": "supply", "cad": "week", "baseline": 100, "inv": False,
                 "interp": "100 위 = 전세 공급부족(수요>공급). 전세·매매 동반 자극."},
    "jr":       {"g": "supply", "cad": "month", "baseline": None, "inv": False,
                 "interp": "전세/매매 비율. 높을수록 갭 부담↓·하방 지지↑."},
    "joutlook": {"g": "supply", "cad": "month", "baseline": 100, "inv": False,
                 "interp": "전세 상승 기대. 전세 불안의 선행 신호."},
    "unsold":   {"g": "fund", "cad": "month", "baseline": None, "inv": True,
                 "interp": "재고. 줄면 수급 양호(상승 신호). ↑는 반대 해석."},
    "rate":     {"g": "fund", "cad": "month", "baseline": None, "inv": True,
                 "interp": "조달비용. 내리면 구매력↑(상승 신호). ↑는 반대 해석."},
}
# 카드 표시 순서(그룹 보기 내 정렬). 선도50은 선행 보조로 매매전망 뒤에 둠.
_INDV2_ORDER = ["buy", "outlook", "lead50", "sale", "jeonse", "volume",
                "jsup", "jr", "joutlook", "unsold", "rate"]
# 연결예정 슬롯 — 데이터 소스 미연결. 가짜 데이터 대신 정직하게 자리만 표시(차트·신호 없음).
_INDV2_PENDING = [
    {"k": "volume", "g": "coin", "lab": "실거래량(수도권)",
     "note": "국토부 실거래 월별 집계 · 다음 자동수집(06:30)부터 채워집니다(최근 24개월)"},
    {"k": "auction", "g": "lead", "lab": "경매 낙찰가율",
     "note": "법원경매 월간 · 데이터 소스 연결 예정"},
    {"k": "supply", "g": "fund", "lab": "입주물량(수도권)",
     "note": "국토부 입주예정 월별 · 연결 예정"},
]

# 엔진 연결 전(또는 DB 비었을 때) 샘플 — 현재 상승장 반영(가짜로 하락처럼 안 보이게)
_IND_SAMPLE = [
    {"key": "sale", "label": "매매가격지수", "sub": "서울 · 주간(KB)", "unit": "", "col": "#B65F5A",
     "series": [94.1, 94.3, 94.6, 94.9, 95.1, 95.4, 95.6, 95.9, 96.1, 96.4,
                96.6, 96.9, 97.1, 97.3, 97.5, 97.7, 97.9, 98.0, 98.1, 98.2]},
    {"key": "jeonse", "label": "전세가격지수", "sub": "서울 · 주간(KB)", "unit": "", "col": "#5A7CA0",
     "series": [95.0, 95.2, 95.4, 95.6, 95.8, 96.0, 96.1, 96.3, 96.4, 96.6,
                96.7, 96.8, 96.9, 97.0, 97.1, 97.2, 97.3, 97.3, 97.4, 97.4]},
    {"key": "volume", "label": "실거래량(수도권)", "sub": "월간 · 국토부 실거래(아파트 매매)", "unit": "건", "col": "#7E9A83",
     "series": [4120, 3980, 4310, 4760, 5210, 4890, 4530, 4180, 3960, 4340,
                4720, 5180, 5460, 5120, 4880, 4610, 4290, 4050, 4480, 4920,
                5240, 5080, 4760, 4530]},
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
    {"key": "unsold", "label": "미분양", "sub": "전국 · 월간(KOSIS)", "unit": "만호", "col": "#8A7C9E",
     "series": [6.9, 6.8, 6.7, 6.6, 6.5, 6.4, 6.3, 6.2, 6.1, 6.0, 5.9, 5.8]},
    {"key": "rate", "label": "주담대 금리", "sub": "월간(한은 ECOS)", "unit": "%", "col": "#9a9b92",
     "series": [4.05, 4.03, 4.00, 3.97, 3.94, 3.91, 3.88, 3.85, 3.82, 3.80, 3.77, 3.74]},
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
    if by.get("unsold"):
        seg.append("공급 부담 " + ("완화" if tr("unsold") < 0
                                else "확대" if tr("unsold") > 0 else "보합"))
    if by.get("rate"):
        seg.append("금리 " + ("하락" if tr("rate") < 0
                            else "상승" if tr("rate") > 0 else "보합"))
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


# ── 주목 단지(거래 활발·상승 + 네이버 검색관심도) ────────────────────────
_SAMPLE_HOT = [
    {"apt": "파크리오", "gu": "송파구", "sd": "seoul", "recent": 14, "prev": 6,
     "vol_chg": 133, "price_eok": "24.8억", "chg": 2.1, "area": "84㎡", "freq": 40, "search": 100},
    {"apt": "헬리오시티", "gu": "송파구", "sd": "seoul", "recent": 12, "prev": 7,
     "vol_chg": 71, "price_eok": "23.5억", "chg": 1.6, "area": "84㎡", "freq": 51, "search": 92},
    {"apt": "잠실엘스", "gu": "송파구", "sd": "seoul", "recent": 9, "prev": 5,
     "vol_chg": 80, "price_eok": "27.0억", "chg": 2.4, "area": "84㎡", "freq": 33, "search": 81},
    {"apt": "래미안원베일리", "gu": "서초구", "sd": "seoul", "recent": 7, "prev": 3,
     "vol_chg": 133, "price_eok": "58.0억", "chg": 3.2, "area": "84㎡", "freq": 18, "search": 88},
    {"apt": "고덕그라시움", "gu": "강동구", "sd": "seoul", "recent": 8, "prev": 6,
     "vol_chg": 33, "price_eok": "17.2억", "chg": 0.9, "area": "84㎡", "freq": 29, "search": 64},
    {"apt": "광교중흥S클래스", "gu": "수원시", "sd": "gg", "recent": 6, "prev": 4,
     "vol_chg": 50, "price_eok": "17.8억", "chg": 1.4, "area": "84㎡", "freq": 16, "search": 55},
]


def fetch_hot_complexes():
    """주목 단지 리스트. 세션/DB metrics의 '_hot' → 샘플 폴백."""
    m = _resolved_metrics()
    if isinstance(m, dict) and m.get("_hot"):
        return m["_hot"]
    return _SAMPLE_HOT


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
@media(max-width:680px){.re-hl{grid-template-columns:1fr;}}
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
def _map_component(regions, groups, trend):
    """지도 탭 단일 화면 컴포넌트(iframe).
    구성: 권역×지표 매트릭스 표(레벨+주간Δ+스파크) → 권역 추이 차트 → 전체폭 확대 지도
         (지도 상단에 범례·지표 토글 오버레이). 권역 선택은 표 행 클릭으로 표/추이/지도 동시 전환.
    regions=시군구 리스트(지도용), groups=권역 레벨 dict, trend=권역 추이 dict."""
    d_json = json.dumps(regions, ensure_ascii=False, separators=(",", ":"))
    g_json = json.dumps(groups, ensure_ascii=False, separators=(",", ":"))
    t_json = json.dumps(trend, ensure_ascii=False, separators=(",", ":"))
    border_json = json.dumps(_BORDER)
    from datetime import date as _date
    asof_json = json.dumps(_date.today().isoformat())
    return (_MAP_HEAD
            + "const D=" + d_json + ";\nconst G=" + g_json
            + ";\nconst T=" + t_json + ";\nconst BORDER=" + border_json
            + ";\nconst ASOF=" + asof_json + ";"
            + _MAP_SCRIPT)


_MAP_HEAD = """
<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{--ink:#34352f;--muted:#9a9b92;--card:#fff;--bg:#FCFCFA;--line:#ECEDE7;--line2:#DEDED7;
  --sage:#7E9A83;--sage2:#A7BBA9;--up:#B65F5A;--dn:#5A7CA0;--jr:#6E8FA8;
  --kfont:'Pretendard',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;}
*{box-sizing:border-box}
body{margin:0;background:transparent;color:var(--ink);font-family:var(--kfont);font-size:14px;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;}
.up{color:var(--up)}.dn{color:var(--dn)}
.hd{display:flex;justify-content:space-between;align-items:flex-end;margin:0 0 12px}
.h1{font-size:18px;font-weight:800;letter-spacing:-.02em}
.hsub{font-size:11.5px;color:var(--muted);margin-top:2px}
.seg{display:inline-flex;border:1px solid var(--line2);border-radius:8px;overflow:hidden;background:var(--card)}
.seg button{border:none;background:none;padding:5px 12px;font-size:11.5px;color:var(--muted);cursor:pointer;
  border-right:1px solid var(--line);font-family:var(--kfont)}
.seg button:last-child{border-right:none}
.seg button.on{background:#EEF1EC;color:var(--ink);font-weight:700}
/* 권역×지표 매트릭스 표 */
table.mx{width:100%;border-collapse:collapse;table-layout:fixed;margin-bottom:0}
/* 권역 펼침(서울 25개 구 등) 시 표만 내부 스크롤 — iframe 전체 높이는 고정 유지 */
.mxscroll{max-height:336px;overflow-y:auto;border:1px solid var(--line);border-radius:11px;margin-bottom:13px}
.mxscroll::-webkit-scrollbar{width:8px}
.mxscroll::-webkit-scrollbar-thumb{background:#E2E3DC;border-radius:6px}
table.mx thead th{position:sticky;top:0;background:var(--card);z-index:2}
table.mx th{font-size:11px;color:var(--muted);font-weight:600;text-align:left;padding:6px 8px}
table.mx td{padding:9px 8px;border-top:1px solid var(--line);vertical-align:middle}
table.mx tr.row{cursor:pointer;transition:background .12s ease}
table.mx tr.row:hover{background:#FAFAF6}
table.mx tr.on{background:#F2F5F0}
table.mx tr.on td:first-child{box-shadow:inset 3px 0 0 var(--sage)}
.rg{font-weight:800;font-size:12.5px}
.lv{font-size:15px;font-weight:800;letter-spacing:-.02em}
.dl{font-size:10.5px;font-weight:700;margin-left:2px}
.spk{vertical-align:middle;margin-left:6px}
/* 추이 패널 */
.panel{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:12px 14px;margin-bottom:13px}
.p-h{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.p-t{font-size:12.5px;font-weight:800}
.p-lg{font-size:10.5px;color:var(--muted);display:flex;gap:12px}
.p-lg i{font-style:normal}.dot{display:inline-block;width:9px;height:9px;border-radius:2px;vertical-align:-1px;margin-right:3px}
.p-read{display:flex;gap:18px;align-items:flex-end;margin-bottom:3px}
.p-read .big{font-size:22px;font-weight:800;letter-spacing:-.02em}
.p-read .sm{font-size:15px;font-weight:800}
.chartwrap{position:relative;width:100%}
#trChart{display:block;width:100%;height:auto}
.vtip{position:absolute;pointer-events:none;background:var(--card);border:1px solid var(--line2);border-radius:7px;
  padding:6px 9px;font-size:11px;opacity:0;transition:opacity .12s;white-space:nowrap;box-shadow:0 4px 14px rgba(52,53,47,.12);z-index:6}
/* 전체폭 지도 + 상단 오버레이 */
.mapwrap{position:relative;width:100%;height:560px;border:1px solid var(--line);border-radius:13px;
  background:var(--bg);overflow:hidden}
.ovl{position:absolute;top:0;left:0;right:0;z-index:3;display:flex;justify-content:space-between;align-items:center;
  gap:10px;padding:8px 12px;background:rgba(252,252,250,.93);border-bottom:1px solid var(--line)}
.leg{display:flex;align-items:center;gap:6px;font-size:10px;color:var(--muted)}
.leg .bar{width:140px;height:11px;border-radius:3px}
.leg .lab{font-weight:700;color:var(--ink);margin-left:6px}
.pills{display:inline-flex;gap:4px}
.pills button{border:none;border-radius:7px;padding:3px 10px;font-size:10.5px;color:var(--muted);cursor:pointer;
  background:transparent;font-family:var(--kfont)}
.pills button.on{background:#EEF1EC;color:var(--ink);font-weight:700}
#map{display:block;width:100%;height:100%}
.dist{stroke:#fff;stroke-width:0.7;cursor:pointer;transition:fill .4s ease,opacity .25s ease}
.dlabel{pointer-events:none;fill:#2f302a;font-family:var(--kfont)}
#hoverLabel{pointer-events:none;font-family:var(--kfont);font-weight:800;fill:#23241d;opacity:0;transition:opacity .1s}
#border{fill:none;stroke:#9DB0A0;stroke-width:1.4;stroke-linejoin:round;pointer-events:none}
.tip{position:absolute;pointer-events:none;background:var(--card);border:1px solid var(--line2);border-radius:8px;
  padding:9px 11px;font-size:12px;min-width:150px;box-shadow:0 6px 22px rgba(52,53,47,.13);opacity:0;
  transform:translateY(4px);transition:opacity .15s,transform .15s;z-index:5}
.note{color:var(--muted);font-size:11px;margin-top:9px;line-height:1.6}
/* 모바일 히트그리드 */
.heatwrap{display:none}
.heat{display:grid;grid-template-columns:repeat(auto-fill,minmax(92px,1fr));gap:7px}
.tile{border:1px solid var(--line);border-radius:10px;padding:8px 9px;position:relative;background:var(--card)}
.tile .tn{font-size:12px;font-weight:700}.tile .tv{font-size:14px;font-weight:800;letter-spacing:-.02em;margin-top:2px}
.tile .tsd{position:absolute;top:7px;right:8px;font-size:9px;color:var(--muted);font-weight:700}
/* 계층 아코디언 표 */
.car{display:inline-block;width:14px;color:var(--muted);font-size:10px;cursor:pointer;user-select:none;text-align:center}
.car:hover{color:var(--ink)}
table.mx tr.childrow td{border-top:1px solid #F4F5EF}
td.child{padding-left:24px !important;font-weight:600;font-size:12.5px;color:#5f5e5a}
td.child .cdot{color:#CDCEC4;margin-right:7px}
.sparse{display:inline-block;margin-left:5px;font-size:9px;color:#86877f;background:#F1EFE8;border-radius:5px;padding:1px 5px;font-weight:700;vertical-align:1px}
.lv.vlow{color:#B7B8AE}
/* 완성형 추이 차트 축 + 각주 */
.axt{fill:var(--muted);font-size:10px;font-family:var(--kfont)}
.axtitle{fill:#6f706a;font-size:10.5px;font-family:var(--kfont)}
.fn{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:10px 13px;font-size:10.8px;
  color:#5f5e5a;line-height:1.65;margin-bottom:13px}
.fn b{color:var(--ink);font-weight:700}
.fn .warn{color:var(--up)}
@media(max-width:680px){.mapwrap{height:420px}.heatwrap{display:block;margin-top:12px}.p-read .big{font-size:19px}}
</style></head><body>
<div class="hd">
  <div><div class="h1">수도권 가격 지도</div><div class="hsub" id="hdSub"></div></div>
  <div class="seg" id="periodSeg"><button data-p="1y">1년</button><button data-p="3y" class="on">3년</button><button data-p="all">전체</button></div>
</div>
<div class="mxscroll"><table class="mx"><thead><tr><th style="width:22%">지역</th><th>매매지수</th><th>전세지수</th><th>거래(건)</th><th>전세가율</th></tr></thead><tbody id="mxBody"></tbody></table></div>
<div class="panel">
  <div class="p-h"><span class="p-t" id="trTitle"></span>
    <span class="p-lg"><i><span class="dot" style="background:#B65F5A"></span>매매</i><i><span class="dot" style="background:#5A7CA0"></span>전세</i></span></div>
  <div class="p-read" id="trRead"></div>
  <div class="chartwrap"><svg id="trChart" viewBox="0 0 620 200" role="img" aria-label="가격지수 추이 차트"></svg><div class="vtip" id="vtip"></div></div>
</div>
<div class="fn">
  <b>매매지수·전세지수란?</b> KB부동산 주간 아파트 가격지수. <b>2022년 1월 10일 = 100.0</b> 기준, 그 시점 대비 현재 매매(전세) 가격 수준을 시가총액 방식으로 지수화한 값입니다(예: 104.2 = 기준시점보다 4.2% 높음). · <b>거래(건)</b> 국토부 실거래 주간 신고 건수 · <b>전세가율</b> 매매가 대비 전세가 비율(KB 월간).
  <span class="warn">※ 지역마다 기준시점 가격수준이 달라, 지수 레벨로 지역 간 가격을 직접 비교할 수는 없습니다(은평 104 &gt; 영등포 101 이라고 은평이 더 비싼 게 아님). 같은 지역의 시간 변화·등락률 비교에 사용하세요.</span>
</div>
<div class="mapwrap" id="mapwrap">
  <div class="ovl"><div class="leg" id="legend"></div>
    <div class="pills" id="metricPills"><button data-m="mm" class="on">매매</button><button data-m="js">전세</button><button data-m="v">거래</button><button data-m="jr">전세가율</button></div></div>
  <svg id="map" viewBox="0 0 1100 1087" preserveAspectRatio="xMidYMid meet" role="img" aria-label="수도권 시군구 지표 지도"></svg>
  <div class="tip" id="tip"></div>
</div>
<div class="heatwrap"><div class="heat" id="heatgrid"></div></div>
<div class="note" id="note"></div>
<script>
"""

_MAP_SCRIPT = r"""
const GK=["gn3","seoul","gg","all"];
const GN3=["강남구","서초구","송파구"];
let region="seoul", metric="mm", period="3y";
let expanded={};

const fmtP=v=>(v>0?"+":"")+(v||0).toFixed(2)+"%";
const fmtL=v=>v==null?"-":(+v).toFixed(1);
const cls=v=>v>0.005?"up":(v<-0.005?"dn":"");
function colMM(v){if(v>=0.30)return"#C16C64";if(v>=0.15)return"#D89089";if(v>=0.05)return"#E9BDB8";if(v>-0.02)return"#EFEEE9";if(v>-0.10)return"#C9D6E5";return"#A9C0DA";}
function colV(v){if(v>=90)return"#6E9A83";if(v>=60)return"#9BBBA3";if(v>=40)return"#BBD2C0";if(v>=25)return"#D8E6DC";return"#EDF3EE";}
function colJR(v){if(v>=68)return"#6E8FA8";if(v>=63)return"#92ABC1";if(v>=58)return"#B4C7D8";if(v>=53)return"#D2DEE9";return"#EBF0F5";}
function fillOf(d){return metric==="v"?colV(d.v):metric==="jr"?colJR(d.jr==null?0:d.jr):colMM(d[metric]);}

function periodN(){return period==="1y"?52:period==="3y"?156:1e9;}
function spark(series,col,w,h){const s=(series||[]).slice(-40);if(s.length<2)return"";
  const mn=Math.min(...s),mx=Math.max(...s),r=(mx-mn)||1;
  const pts=s.map((v,i)=>`${(i/(s.length-1)*w).toFixed(1)},${(h-2-(v-mn)/r*(h-4)).toFixed(1)}`).join(" ");
  return `<svg class="spk" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.5"/></svg>`;}

function isLeaf(k){return !GK.includes(k);}
function rowHTML(g,k,child){
  const on=k===region?" on":"";
  const mc=cls(g.sale_wk),jc=cls(g.jeonse_wk),vc=cls((g.vc||0)/100);
  const tk=T[k]||{};
  const kids=g.children&&g.children.length;
  const car=kids?`<span class="car" data-exp="${k}">${expanded[k]?"▾":"▸"}</span>`
                :(child?`<span class="cdot">·</span>`:`<span class="car"></span>`);
  const vNum=g.v||0, low=child&&vNum<15;
  const sparse=low?`<span class="sparse">표본 적음</span>`:"";
  return `<tr class="row${child?" childrow":""}${on}" data-k="${k}">
    <td class="${child?"child":"rg"}">${car}${g.name}</td>
    <td><span class="lv">${fmtL(g.sale)}</span><span class="dl ${mc}">${fmtP(g.sale_wk)}</span>${child?"":spark(tk.sale,"#B65F5A",46,16)}</td>
    <td><span class="lv">${fmtL(g.jeonse)}</span><span class="dl ${jc}">${fmtP(g.jeonse_wk)}</span></td>
    <td><span class="lv${low?" vlow":""}">${vNum.toLocaleString()}</span><span class="dl ${vc}">${(g.vc||0)>0?"+":""}${g.vc||0}%</span>${sparse}</td>
    <td><span class="lv">${g.jr==null?"-":g.jr+"%"}</span></td></tr>`;
}
function renderTable(){
  let html="";
  GK.forEach(k=>{const g=G[k];if(!g)return;
    html+=rowHTML(g,k,false);
    if(expanded[k]&&g.children){g.children.forEach(cn=>{const cg=G[cn];if(cg)html+=rowHTML(cg,cn,true);});}});
  const body=document.getElementById("mxBody");body.innerHTML=html;
  body.querySelectorAll(".car[data-exp]").forEach(c=>c.onclick=e=>{
    e.stopPropagation();const k=c.dataset.exp;expanded[k]=!expanded[k];renderTable();});
  body.querySelectorAll("tr.row").forEach(tr=>tr.onclick=()=>{const k=tr.dataset.k;region=k;
    if(!isLeaf(k)&&G[k].children&&G[k].children.length)expanded[k]=true;refresh();});}

function sliceP(arr){const n=periodN();return (arr||[]).slice(-n);}
function niceTicks(mn,mx){const span=(mx-mn)||1,raw=span/3;
  const mag=Math.pow(10,Math.floor(Math.log10(raw)));
  const cands=[1,2,2.5,5,10].map(m=>m*mag);
  const step=cands.find(c=>c>=raw)||cands[cands.length-1];
  const lo=Math.ceil(mn/step)*step,ts=[];
  for(let v=lo;v<=mx+1e-9&&ts.length<6;v+=step)ts.push(+v.toFixed(2));
  return ts.length?ts:[mn,mx];}
const _ASOF=new Date(ASOF+"T00:00:00");
function tickDate(i,n){const d=new Date(_ASOF);d.setDate(d.getDate()-(n-1-i)*7);return d;}
function fmtMon(d){return "'"+String(d.getFullYear()).slice(2)+"."+(d.getMonth()+1);}

function renderTrend(){const g=G[region]||{};const tk=T[region]||{};
  const sale=sliceP(tk.sale),jeon=sliceP(tk.jeonse);
  document.getElementById("trTitle").textContent=(g.name||"")+" 가격지수 추이";
  document.getElementById("trRead").innerHTML=
    `<div><span style="font-size:11px;color:#9a9b92">매매</span> <span class="big">${fmtL(g.sale)}</span> <span class="${cls(g.sale_wk)}" style="font-weight:800;font-size:12.5px">${(g.sale_wk||0)>=0?"▲":"▼"} ${fmtP(g.sale_wk)}</span></div>`
   +`<div style="padding-bottom:2px"><span style="font-size:11px;color:#9a9b92">전세</span> <span class="sm" style="color:#5A7CA0">${fmtL(g.jeonse)}</span> <span class="${cls(g.jeonse_wk)}" style="font-size:11px">${fmtP(g.jeonse_wk)}</span></div>`;
  const svg=document.getElementById("trChart");
  const all=sale.concat(jeon).filter(v=>v!=null);
  if(all.length<2){svg.innerHTML="";return;}
  const L=64,Rr=606,T0=14,B=150,W=Rr-L,Hh=B-T0,n=sale.length;
  const dmn=Math.min(...all),dmx=Math.max(...all);
  const ticks=niceTicks(dmn,dmx);
  const lo=Math.min(dmn,ticks[0]),hi=Math.max(dmx,ticks[ticks.length-1]),rr=(hi-lo)||1;
  const X=i=>L+(n<=1?0:i/(n-1)*W), Y=v=>B-(v-lo)/rr*Hh;
  const line=s=>s.map((v,i)=>v==null?"":`${(i&&s[i-1]!=null)?"L":"M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const area=`M${X(0).toFixed(1)},${B} `+sale.map((v,i)=>`L${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ")+` L${X(n-1).toFixed(1)},${B} Z`;
  let grid="";
  ticks.forEach(tv=>{const y=(+Y(tv)).toFixed(1);
    grid+=`<line x1="${L}" y1="${y}" x2="${Rr}" y2="${y}" stroke="#F0F1EB"/>`
        +`<text class="axt" x="${L-7}" y="${(+y+3).toFixed(1)}" text-anchor="end">${tv.toFixed(tv%1?1:0)}</text>`;});
  let xt="";
  for(let j=0;j<4;j++){const i=Math.round(j/3*(n-1));
    xt+=`<text class="axt" x="${X(i).toFixed(1)}" y="${B+16}" text-anchor="middle">${fmtMon(tickDate(i,n))}</text>`;}
  const ycy=((T0+B)/2).toFixed(0);
  svg.innerHTML=grid
   +`<line x1="${L}" y1="${B}" x2="${Rr}" y2="${B}" stroke="#D7D8D0"/>`
   +`<path d="${area}" fill="#B65F5A" opacity="0.08"/>`
   +`<path d="${line(sale)}" fill="none" stroke="#B65F5A" stroke-width="2"/>`
   +`<path d="${line(jeon)}" fill="none" stroke="#5A7CA0" stroke-width="1.7" stroke-dasharray="4 3"/>`
   +xt
   +`<text class="axtitle" x="${((L+Rr)/2).toFixed(0)}" y="194" text-anchor="middle">가로축 — 시점(주간, 매주 월요일 기준)</text>`
   +`<text class="axtitle" x="13" y="${ycy}" text-anchor="middle" transform="rotate(-90 13 ${ycy})">세로축 — 가격지수 (2022.1.10=100)</text>`
   +`<line class="vx" x1="${L}" x2="${L}" y1="${T0}" y2="${B}" stroke="#B9BBB0" stroke-dasharray="3 3" opacity="0"/>`
   +`<circle class="vd1" r="3" fill="#B65F5A" opacity="0"/><circle class="vd2" r="2.6" fill="#5A7CA0" opacity="0"/>`;
  const vtip=document.getElementById("vtip");
  const vx=svg.querySelector(".vx"),vd1=svg.querySelector(".vd1"),vd2=svg.querySelector(".vd2");
  svg.onmousemove=e=>{const b=svg.getBoundingClientRect();const ux=(e.clientX-b.left)/b.width*620;
    let i=Math.round((ux-L)/W*(n-1));i=Math.max(0,Math.min(n-1,i));
    const x=X(i);vx.setAttribute("x1",x);vx.setAttribute("x2",x);vx.style.opacity="1";
    if(sale[i]!=null){vd1.setAttribute("cx",x);vd1.setAttribute("cy",Y(sale[i]));vd1.style.opacity="1";}else vd1.style.opacity="0";
    if(jeon[i]!=null){vd2.setAttribute("cx",x);vd2.setAttribute("cy",Y(jeon[i]));vd2.style.opacity="1";}else vd2.style.opacity="0";
    vtip.innerHTML=`<b>${fmtMon(tickDate(i,n))}</b> · 매매 <b>${fmtL(sale[i])}</b> · 전세 <b style="color:#5A7CA0">${fmtL(jeon[i])}</b>`;
    let lx=e.clientX-b.left+12;if(lx>b.width-160)lx-=170;vtip.style.left=lx+"px";vtip.style.top="2px";vtip.style.opacity="1";};
  svg.onmouseleave=()=>{vx.style.opacity="0";vd1.style.opacity="0";vd2.style.opacity="0";vtip.style.opacity="0";};}

function pathNums(d){return (d.match(/-?\d+\.?\d*/g)||[]).map(Number);}
function bboxOf(list){let x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;list.forEach(d=>{const n=pathNums(d.d);
    for(let i=0;i+1<n.length;i+=2){const x=n[i],y=n[i+1];if(x<x0)x0=x;if(x>x1)x1=x;if(y<y0)y0=y;if(y>y1)y1=y;}});
  if(x1<x0)return[0,0,1100,1087];const padX=(x1-x0)*0.06,padY=(y1-y0)*0.06;
  return [x0-padX,y0-padY,(x1-x0)+2*padX,(y1-y0)+2*padY];}
function activeSet(){
  if(GK.includes(region)){
    if(region==="gn3")return D.filter(d=>GN3.includes(d.n));
    if(region==="seoul")return D.filter(d=>d.sd==="seoul");
    if(region==="gg")return D.filter(d=>d.sd==="gg");return D;}
  const one=D.filter(d=>d.n===region);return one.length?one:D;}
function inActive(d){
  if(GK.includes(region)){
    if(region==="gn3")return GN3.includes(d.n);
    if(region==="seoul")return d.sd==="seoul";
    if(region==="gg")return d.sd==="gg";return true;}
  return D.some(x=>x.n===region)?(d.n===region):true;}

function placeLabels(){const act=activeSet();const big=act.length<=6;
  const cand=[...act].sort((a,b)=>b.ar-a.ar);const placed=[],out=[];
  for(const d of cand){const fs=big?15:(d.sd==="seoul"?10:12);const w=d.sl.length*fs*0.62,h=fs;
    if(!big&&d.sd==="gg"&&d.ar<420)continue;
    const box=[d.cx-w/2,d.cy-h/2,d.cx+w/2,d.cy+h/2];let ok=true;
    for(const p of placed){if(!(box[2]<p[0]||box[0]>p[2]||box[3]<p[1]||box[1]>p[3])){ok=false;break;}}
    if(!ok)continue;placed.push(box);
    out.push(`<text class="dlabel" x="${d.cx}" y="${d.cy}" text-anchor="middle" dominant-baseline="middle" font-size="${fs}" font-weight="${d.sd==="seoul"?700:600}" paint-order="stroke" stroke="#FCFCFA" stroke-width="2" stroke-linejoin="round">${d.sl}</text>`);}
  return out.join("");}

let hovered=null;
function drawMap(){const svg=document.getElementById("map");
  svg.setAttribute("viewBox",bboxOf(activeSet()).map(v=>v.toFixed(1)).join(" "));
  const ps=D.map((d,i)=>{const dim=!inActive(d);
    return `<path class="dist" data-i="${i}" d="${d.d}" fill="${fillOf(d)}" style="opacity:${dim?0.12:1};pointer-events:${dim?"none":"auto"}"></path>`;}).join("");
  svg.innerHTML=`<g id="paths">${ps}</g><path id="border" d="${BORDER}"></path><g id="labels">${placeLabels()}</g>`
    +`<text id="hoverLabel" text-anchor="middle" dominant-baseline="middle" paint-order="stroke" stroke="#FCFCFA" stroke-width="2.6" stroke-linejoin="round"></text>`;
  const wrap=document.getElementById("mapwrap"),tip=document.getElementById("tip"),pg=svg.querySelector("#paths"),hl=svg.querySelector("#hoverLabel");
  hovered=null;
  function clearHover(){if(hovered){hovered.style.stroke="#fff";hovered.style.strokeWidth="0.7";hovered=null;}hl.style.opacity="0";tip.style.opacity="0";tip.style.transform="translateY(4px)";}
  svg.querySelectorAll("path.dist").forEach(p=>{
    p.onmouseenter=()=>{clearHover();hovered=p;p.style.stroke="#7E9A83";p.style.strokeWidth="1.5";pg.appendChild(p);
      const d=D[+p.dataset.i];showTip(d,tip);tip.style.opacity="1";tip.style.transform="translateY(0)";
      hl.setAttribute("x",d.cx);hl.setAttribute("y",d.cy);hl.setAttribute("font-size",d.sd==="seoul"?14:16);hl.textContent=d.sl;hl.style.opacity="1";};
    p.onmouseleave=()=>clearHover();});
  wrap.onmouseleave=()=>clearHover();
  wrap.onmousemove=e=>{const r=wrap.getBoundingClientRect();let x=e.clientX-r.left+14,y=e.clientY-r.top+14;
    if(x>r.width-180)x=e.clientX-r.left-168;if(y>r.height-90)y=e.clientY-r.top-80;tip.style.left=x+"px";tip.style.top=y+"px";};}
function showTip(d,tip){tip.innerHTML=`<div style="font-weight:700;margin-bottom:5px">${d.n} <span style="font-weight:400;color:#9a9b92">${d.sd==="seoul"?"서울":"경기"}</span></div>
  <div style="color:#9a9b92">매매 <span class="${cls(d.mm)}">${fmtP(d.mm)}</span> · 전세 <span class="${cls(d.js)}">${fmtP(d.js)}</span></div>
  <div style="color:#9a9b92">거래 ${d.v}건 <span class="${cls(d.vc/100)}">(${d.vc>0?"+":""}${d.vc}%)</span></div>
  <div style="color:#9a9b92">전세가율 ${d.jr==null?"-":d.jr+"%"}</div>`;}

function drawLegend(){let html="";
  if(metric==="v"){html=grad("#EDF3EE","#6E9A83","적음","많음","거래량");}
  else if(metric==="jr"){html=grad("#EBF0F5","#6E8FA8","낮음","높음","전세가율");}
  else{html=`<span>하락</span><span class="bar" style="background:linear-gradient(90deg,#A9C0DA,#C9D6E5,#EFEEE9,#E9BDB8,#D89089,#C16C64)"></span><span>상승</span><span class="lab">${metric==="mm"?"매매":"전세"} 등락</span>`;}
  document.getElementById("legend").innerHTML=html;}
function grad(c0,c1,l0,l1,lab){return `<span>${l0}</span><span class="bar" style="background:linear-gradient(90deg,${c0},${c1})"></span><span>${l1}</span><span class="lab">${lab}</span>`;}

function buildHeat(){const pool=activeSet();const k=metric==="v"?"v":metric;
  const sorted=[...pool].sort((a,b)=>((b[k]==null?-1e9:b[k]))-((a[k]==null?-1e9:a[k])));
  document.getElementById("heatgrid").innerHTML=sorted.map(d=>{const c=fillOf(d);
    const val=metric==="v"?d.v+"건":metric==="jr"?(d.jr==null?"-":d.jr+"%"):fmtP(d[metric]);
    const tc=(metric==="v"||metric==="jr")?"#34352f":(d[metric]>=0?"#B65F5A":"#5A7CA0");
    return `<div class="tile" style="border-color:${c}"><span class="tsd">${d.sd==="seoul"?"서울":"경기"}</span><div class="tn">${d.sl}</div><div class="tv" style="color:${tc}">${val}</div></div>`;}).join("");}

function updateHead(){const g=G[region]||{};
  document.getElementById("hdSub").textContent=(g.name||"")+" · 매매 "+fmtL(g.sale)+" "+fmtP(g.sale_wk)+" · 전세 "+fmtL(g.jeonse)+" "+fmtP(g.jeonse_wk);
  document.getElementById("note").textContent="표에서 ▸를 누르면 하위 시군구가 펼쳐집니다(서울 25개 구·경기 시 단위) · 행을 누르면 추이·지도가 그 지역으로 전환 · 지도 색=선택 지표(빨강 상승/파랑 하락) · 거래는 주간 실거래(시군구는 표본이 작아 변동 큼) · 매매·전세=KB 주간지수, 전세가율=KB";}

function refresh(){renderTable();renderTrend();drawLegend();drawMap();buildHeat();updateHead();}
document.querySelectorAll("#periodSeg button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#periodSeg button").forEach(x=>x.classList.remove("on"));b.classList.add("on");period=b.dataset.p;renderTrend();});
document.querySelectorAll("#metricPills button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#metricPills button").forEach(x=>x.classList.remove("on"));b.classList.add("on");metric=b.dataset.m;drawLegend();drawMap();buildHeat();});
refresh();
</script></body></html>
"""


# ── 서브탭 렌더러 ───────────────────────────────────────────────
def _render_map():
    g, t = fetch_region_levels()
    components.html(_map_component(_merged_regions(), g, t),
                    height=1430, scrolling=False)


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
        st.caption("추이 데이터가 아직 없어요. 매일 06:30 수집 후 표시됩니다.")
        return
    asof = date.today().strftime("%Y-%m-%d")
    components.html(_trend_component(inds, asof), height=508, scrolling=False)
    st.caption("매매·전세가격지수(KB 주간) · 전세가율(KB 월간) — 카드를 누르면 위에서 크게 · "
               "기간 토글 동기화 · 코스피·코스닥 차트와 동일 양식")


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
 --sage:#A7BBA9;--sage2:#7E9A83;--up:#B65F5A;--dn:#5A7CA0;
 --kfont:'Pretendard',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--kfont);font-size:14px;-webkit-font-smoothing:antialiased}
.box{padding:2px 1px 6px}
.cycle{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:15px 17px;margin-bottom:14px}
.cyc-top{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:11px}
.cyc-top .t{font-size:13px;font-weight:800}
.cyc-top .now{font-size:12px;color:var(--muted)}.cyc-top .now b{color:var(--up)}
.stages{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:9px}
.stage{text-align:center;font-size:12px;font-weight:700;color:var(--muted);padding:9px 4px;border-radius:10px;background:#F4F5F0;border:1px solid transparent}
.stage.on{background:#FBEEED;color:var(--up);border-color:#E7C9C5}
.stage small{display:block;font-size:9.5px;font-weight:600;color:var(--muted);margin-top:1px}
.stage.on small{color:#B07A75}
.cyc-read{font-size:12px;color:var(--muted);line-height:1.5}.cyc-read b{color:var(--ink)}
.controls{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px;margin:4px 0 13px}
.seg{display:inline-flex;border:1px solid var(--line2);border-radius:8px;overflow:hidden;background:var(--card)}
.seg button{border:none;background:none;padding:6px 13px;font-size:12px;color:var(--muted);cursor:pointer;border-right:1px solid var(--line);font-family:var(--kfont)}
.seg button:last-child{border-right:none}.seg button.on{background:#EEF1EC;color:var(--ink);font-weight:700}
.hero{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:15px 17px 11px;margin-bottom:15px}
.hero-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin-bottom:5px}
.hero-lab{font-size:12.5px;font-weight:600;color:var(--muted);display:flex;align-items:center;gap:7px}
.hero-val{font-size:30px;font-weight:800;letter-spacing:-.03em;line-height:1;margin-top:3px}
.hero-val .u{font-size:14px;font-weight:600;color:var(--muted);margin-left:3px}
.hero-note{font-size:11.5px;color:var(--muted);margin-top:7px;line-height:1.5}
.chart{position:relative;width:100%}.chart svg{display:block;width:100%;overflow:visible}
.axis{font-size:9.5px;fill:var(--muted)}
.tip{position:absolute;pointer-events:none;background:#fff;border:1px solid var(--line2);border-radius:8px;padding:6px 9px;font-size:11.5px;box-shadow:0 6px 18px rgba(52,53,47,.13);opacity:0;transition:opacity .12s;white-space:nowrap;z-index:6}
.tip b{font-weight:800}.tip .d{color:var(--muted);font-size:10.5px}
.ghead{display:flex;align-items:center;gap:9px;margin:16px 2px 9px}
.ghead .gn{font-size:13px;font-weight:800}.ghead .gd{font-size:11px;color:var(--muted)}
.ghead .gsig{margin-left:auto;font-size:11px;font-weight:800;padding:2px 9px;border-radius:20px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:11px 12px 8px;cursor:pointer;transition:transform .16s,box-shadow .16s,border-color .16s}
.card:hover{transform:translateY(-2px);box-shadow:0 6px 16px rgba(52,53,47,.08);border-color:var(--sage)}
.card.on{border-color:var(--sage2);box-shadow:inset 0 0 0 1.5px var(--sage2)}
.card.pend{cursor:default;background:#FAFAF7;border-style:dashed;opacity:.85}
.card.pend:hover{transform:none;box-shadow:none;border-color:var(--line2)}
.c-lab{font-size:12px;font-weight:700;color:var(--ink)}
.c-chips{display:flex;gap:4px;margin-top:3px;flex-wrap:wrap}
.chip{font-size:9px;font-weight:800;border-radius:5px;padding:1px 5px;letter-spacing:.02em}
.chip.week{background:#F3EEE6;color:#8A6E45}.chip.month{background:#EEF1EC;color:#5E7363}
.chip.pend{background:#F1F0EC;color:#8A8576}
.c-val{font-size:18px;font-weight:800;letter-spacing:-.02em;margin:6px 0 3px}
.c-val .u{font-size:10px;color:var(--muted);margin-left:1px}.c-val .bl{font-size:9px;color:var(--muted);font-weight:700;margin-left:5px}
.sig{display:inline-flex;align-items:center;gap:4px;font-size:10.5px;font-weight:800;padding:2px 8px;border-radius:20px;margin-bottom:5px}
.sig.up{color:var(--up);background:#FBEEED}.sig.dn{color:var(--dn);background:#EAF0F7}.sig.fl{color:var(--muted);background:#F1F2EC}
.sig .inv{font-size:8.5px;font-weight:700;color:var(--muted);background:#fff;border:1px solid var(--line2);border-radius:4px;padding:0 3px;margin-left:2px}
.c-spark{width:100%;height:34px;display:block;overflow:visible}
.c-interp{font-size:10.5px;color:var(--muted);line-height:1.45;margin-top:6px}
.c-pendnote{font-size:10.5px;color:var(--muted);line-height:1.45;margin-top:10px}
.gtag{font-size:9px;font-weight:800;color:var(--muted);background:#F4F5F0;border-radius:5px;padding:1px 6px;margin-left:6px}
.subnote{font-size:11px;color:var(--muted);margin:10px 2px 2px}
@media(max-width:680px){.grid{grid-template-columns:repeat(2,1fr)}}
</style></head><body><div class="box">
  <div class="cycle">
    <div class="cyc-top"><span class="t">부동산 사이클 위치</span>
      <span class="now">선행·심리 종합 → 현재 <b id="nowStage"></b></span></div>
    <div class="stages" id="stages"></div>
    <div class="cyc-read" id="cycRead"></div>
  </div>
  <div class="controls">
    <span style="font-size:11.5px;color:var(--muted)" id="viewDesc"></span>
    <div style="display:flex;gap:8px">
      <span class="seg" id="view"><button data-v="group" class="on">기능별 그룹</button><button data-v="signal">신호 강도순</button></span>
      <span class="seg" id="period"><button data-p="1Y">1년</button><button data-p="3Y">3년</button><button data-p="ALL" class="on">전체</button></span>
    </div>
  </div>
  <div class="hero">
    <div class="hero-head"><div><div class="hero-lab" id="hLab"></div><div class="hero-val" id="hVal"></div></div>
      <div class="sig" id="hSig" style="font-size:12px;padding:3px 11px"></div></div>
    <div class="chart" id="hChart"></div>
    <div class="hero-note" id="hNote"></div>
  </div>
  <div id="body"></div>
</div>
<script>
const IND=__IND__,PEND=__PEND__,G=__G__;
const ASOF=new Date("__ASOF__T00:00:00");
const MON=["1월","2월","3월","4월","5월","6월","7월","8월","9월","10월","11월","12월"];
const DAYS={"1Y":365,"3Y":1095};const GORDER=["lead","coin","supply","fund"];
let period="ALL",view="group",focusK=IND.length?IND[0].k:null;
function byK(k){return IND.find(d=>d.k===k);}
function makeSeries(m,p){const step=m.cad==="month"?30:7;
 const need=p==="ALL"?m.real.length:Math.min(m.real.length,Math.round(DAYS[p]/step)+1);
 const vals=m.real.slice(-need);
 return vals.map((v,i)=>({t:new Date(ASOF.getTime()-(vals.length-1-i)*step*86400000),v}));}
function fmtV(m,v){const b=Math.abs(m.base||v);if(b>=1000)return Math.round(v).toLocaleString();
 if(b<10)return (Math.round(v*100)/100).toFixed(2);return (Math.round(v*10)/10).toFixed(1);}
function signal(m,pts){const a=pts[0].v,b=pts[pts.length-1].v;let dir=(b-a)/Math.abs(a||1);
 if(m.inv)dir=-dir;
 if(m.baseline!=null){const lvl=(b-m.baseline)/m.baseline;dir=dir*0.6+lvl*0.8;}
 const cls=dir>0.012?"up":dir<-0.012?"dn":"fl";
 return {cls,txt:cls==="up"?"상승 신호":cls==="dn"?"하락 신호":"중립",score:dir};}
function drawChart(host,m,pts,h,longR){const W=600,P={l:4,r:4,t:8,b:16};
 const xs=i=>P.l+i/(pts.length-1)*(W-P.l-P.r);
 let lo=Math.min.apply(null,pts.map(p=>p.v)),hi=Math.max.apply(null,pts.map(p=>p.v));
 if(m.baseline!=null){lo=Math.min(lo,m.baseline);hi=Math.max(hi,m.baseline);}
 const sp=(hi-lo)||1;const y0=lo-sp*0.14,y1=hi+sp*0.14;
 const ys=v=>P.t+(1-(v-y0)/(y1-y0))*(h-P.t-P.b);
 let path=pts.map((p,i)=>(i?"L":"M")+xs(i).toFixed(1)+" "+ys(p.v).toFixed(1)).join(" ");
 let area=path+" L"+xs(pts.length-1).toFixed(1)+" "+(h-P.b)+" L"+xs(0).toFixed(1)+" "+(h-P.b)+" Z";
 let bl="";if(m.baseline!=null){const by=ys(m.baseline).toFixed(1);
  bl='<line x1="'+P.l+'" y1="'+by+'" x2="'+(W-P.r)+'" y2="'+by+'" stroke="#C9CBC2" stroke-width="1" stroke-dasharray="4 4"/>'
   +'<text class="axis" x="'+(W-P.r)+'" y="'+(by-3)+'" text-anchor="end">기준 '+m.baseline+'</text>';}
 let tk="",last=null;pts.forEach((p,i)=>{const key=longR?p.t.getFullYear():p.t.getMonth();
  if(key!==last){last=key;const x=xs(i);if(x>12&&x<W-12){const lab=longR?("'"+String(p.t.getFullYear()).slice(2)):MON[p.t.getMonth()];
   tk+='<text class="axis" x="'+x.toFixed(1)+'" y="'+(h-4)+'" text-anchor="middle">'+lab+'</text>';}}});
 host.innerHTML='<svg viewBox="0 0 '+W+' '+h+'" preserveAspectRatio="none" style="height:'+h+'px">'
  +'<path d="'+area+'" fill="'+m.col+'" opacity="0.11"/>'+bl
  +'<path d="'+path+'" fill="none" stroke="'+m.col+'" stroke-width="2" stroke-linejoin="round"/>'
  +'<line class="vx" x1="0" x2="0" y1="'+P.t+'" y2="'+(h-P.b)+'" stroke="#B9BBB0" stroke-width="1" stroke-dasharray="3 3" opacity="0"/>'
  +'<circle class="cp" r="3.4" fill="'+m.col+'" opacity="0"/>'+tk+'</svg>';
 const svg=host.querySelector("svg"),vx=host.querySelector(".vx"),cp=host.querySelector(".cp");
 let tip=host.querySelector(".tip");if(!tip){tip=document.createElement("div");tip.className="tip";host.appendChild(tip);}
 svg.onmousemove=e=>{const r=svg.getBoundingClientRect();const px=(e.clientX-r.left)/r.width*W;
  let i=Math.round((px-P.l)/((W-P.l-P.r))*(pts.length-1));i=Math.max(0,Math.min(pts.length-1,i));
  const x=xs(i),yv=ys(pts[i].v);vx.setAttribute("x1",x);vx.setAttribute("x2",x);vx.setAttribute("opacity","1");
  cp.setAttribute("cx",x);cp.setAttribute("cy",yv);cp.setAttribute("opacity","1");const d=pts[i].t;
  tip.innerHTML="<b>"+fmtV(m,pts[i].v)+m.unit+"</b> <span class='d'>"+d.getFullYear()+"."+String(d.getMonth()+1).padStart(2,"0")+"</span>";
  tip.style.opacity="1";let tx=(x/W)*r.width+10;if(tx>r.width-110)tx-=120;tip.style.left=tx+"px";tip.style.top=(yv/h*r.height-30)+"px";};
 svg.onmouseleave=()=>{vx.setAttribute("opacity","0");cp.setAttribute("opacity","0");tip.style.opacity="0";};}
function sparkSVG(m,pts){const W=200,H=34,P=3;const xs=i=>i/(pts.length-1)*W;
 let lo=Math.min.apply(null,pts.map(p=>p.v)),hi=Math.max.apply(null,pts.map(p=>p.v));const sp=(hi-lo)||1;
 const ys=v=>P+(1-(v-lo)/sp)*(H-2*P);
 const path=pts.map((p,i)=>(i?"L":"M")+xs(i).toFixed(1)+" "+ys(p.v).toFixed(1)).join(" ");
 const area=path+" L"+W+" "+H+" L0 "+H+" Z";
 return '<svg class="c-spark" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none"><path d="'+area+'" fill="'+m.col+'" opacity="0.1"/><path d="'+path+'" fill="none" stroke="'+m.col+'" stroke-width="1.7"/></svg>';}
function cardHTML(m,withTag){const pts=makeSeries(m,period);const s=signal(m,pts);
 const chips='<span class="chip '+m.cad+'">'+(m.cad==="month"?"월간":"주간")+'</span>';
 const bl=m.baseline!=null?'<span class="bl">기준 '+m.baseline+'</span>':'';
 const inv=m.inv?'<span class="inv">역행</span>':'';
 const gtag=withTag?'<span class="gtag">'+G[m.g].name+'</span>':'';
 return '<div class="card '+(m.k===focusK?"on":"")+'" data-k="'+m.k+'">'
  +'<div><div class="c-lab">'+m.lab+gtag+'</div><div class="c-chips">'+chips+'</div></div>'
  +'<div class="c-val">'+fmtV(m,m.base)+'<span class="u">'+m.unit+'</span>'+bl+'</div>'
  +'<div class="sig '+s.cls+'">'+(s.cls==="up"?"▲":s.cls==="dn"?"▼":"●")+' '+s.txt+inv+'</div>'
  +sparkSVG(m,pts)+'<div class="c-interp">'+m.interp+'</div></div>';}
function pendCardHTML(p){return '<div class="card pend">'
  +'<div><div class="c-lab">'+p.lab+'</div><div class="c-chips"><span class="chip pend">연결예정</span></div></div>'
  +'<div class="c-pendnote">'+p.note+'</div></div>';}
function bindCards(){document.querySelectorAll(".card:not(.pend)").forEach(c=>c.onclick=()=>{focusK=c.dataset.k;renderFocus();
 document.querySelectorAll(".card:not(.pend)").forEach(x=>x.classList.toggle("on",x.dataset.k===focusK));});}
function gsig(ms){if(!ms.length)return null;let sc=0;ms.forEach(m=>sc+=signal(m,makeSeries(m,period)).score);sc/=ms.length;
 const cls=sc>0.02?"up":sc<-0.02?"dn":"fl";return {txt:cls==="up"?"종합 상승":cls==="dn"?"종합 하락":"종합 중립",
  bg:cls==="up"?"#FBEEED":cls==="dn"?"#EAF0F7":"#F1F2EC",fg:cls==="up"?"#B65F5A":cls==="dn"?"#5A7CA0":"#9a9b92"};}
function renderBody(){const host=document.getElementById("body");
 if(view==="group"){let html="";for(const gk of GORDER){const ms=IND.filter(m=>m.g===gk);const ps=PEND.filter(p=>p.g===gk);
   if(!ms.length&&!ps.length)continue;const gs=gsig(ms);
   html+='<div class="ghead"><span class="gn">'+G[gk].name+'</span><span class="gd">'+G[gk].desc+'</span>'
    +(gs?'<span class="gsig" style="background:'+gs.bg+';color:'+gs.fg+'">'+gs.txt+'</span>':'')+'</div>'
    +'<div class="grid">'+ms.map(m=>cardHTML(m,false)).join("")+ps.map(pendCardHTML).join("")+'</div>';}
  host.innerHTML=html;
 }else{const sorted=[...IND].sort((a,b)=>signal(b,makeSeries(b,period)).score-signal(a,makeSeries(a,period)).score);
  host.innerHTML='<div class="ghead"><span class="gn">신호 강도순</span><span class="gd">강한 호재 → 악재</span></div>'
   +'<div class="grid">'+sorted.map(m=>cardHTML(m,true)).join("")+'</div>'
   +(PEND.length?'<div class="subnote">연결예정 '+PEND.length+'종('+PEND.map(p=>p.lab).join("·")+')은 그룹 보기에서 확인</div>':'');}
 bindCards();}
function renderFocus(){const m=byK(focusK);if(!m)return;const pts=makeSeries(m,period);const s=signal(m,pts);const longR=period!=="1Y";
 document.getElementById("hLab").innerHTML='<span class="chip '+m.cad+'">'+(m.cad==="month"?"월간":"주간")+'</span>'+m.lab+' · '+m.sub;
 document.getElementById("hVal").innerHTML=fmtV(m,m.base)+'<span class="u">'+m.unit+'</span>';
 const hs=document.getElementById("hSig");hs.className="sig "+s.cls;hs.style.fontSize="12px";hs.style.padding="3px 11px";
 hs.innerHTML=(s.cls==="up"?"▲":s.cls==="dn"?"▼":"●")+' '+s.txt+(m.inv?'<span class="inv">역행</span>':'');
 document.getElementById("hNote").textContent=m.interp;
 drawChart(document.getElementById("hChart"),m,pts,210,longR);}
function renderCycle(){const order=["침체기","회복기","상승기","둔화기"];
 const subs={"침체기":"가격↓ 거래↓","회복기":"심리·거래 반등","상승기":"가격·심리 강세","둔화기":"상승폭 축소"};
 const lead=IND.filter(m=>m.g==="lead"||m.k==="jsup");let cur="회복기";
 if(lead.length){let sc=0;lead.forEach(m=>sc+=signal(m,makeSeries(m,period)).score);sc/=lead.length;
  cur=sc>0.05?"상승기":sc>0.0?"회복기":sc>-0.05?"둔화기":"침체기";}
 document.getElementById("nowStage").textContent=cur;
 document.getElementById("stages").innerHTML=order.map(s=>'<div class="stage '+(s===cur?"on":"")+'">'+s+'<small>'+subs[s]+'</small></div>').join("");
 document.getElementById("cycRead").innerHTML='선행지표(매수우위·전망·선도50)와 전세수급을 종합해 <b>'+cur+'</b>로 판정. 국면 전환은 매수우위·전망지수가 기준 100을 위아래로 넘을 때 먼저 신호가 나와요.';}
document.querySelectorAll("#view button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#view button").forEach(x=>x.classList.remove("on"));b.classList.add("on");view=b.dataset.v;
 document.getElementById("viewDesc").textContent=view==="group"?"기능별로 묶어 의미 파악":"호재·악재 강한 순으로 정렬";renderBody();});
document.querySelectorAll("#period button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#period button").forEach(x=>x.classList.remove("on"));b.classList.add("on");period=b.dataset.p;renderCycle();renderFocus();renderBody();});
document.getElementById("viewDesc").textContent="기능별로 묶어 의미 파악";
renderCycle();renderFocus();renderBody();
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
    # 연결예정 슬롯은 '아직 수집 안 된' 것만 표시(실데이터가 들어오면 자동으로 라이브 전환).
    live_keys = {d["k"] for d in ind}
    pend = [p for p in _INDV2_PENDING if p["k"] not in live_keys]
    return ind, pend


def _indicator_chart_component(ind, pend, asof):
    import json as _json
    return (_INDV2_HTML
            .replace("__IND__", _json.dumps(ind, ensure_ascii=False))
            .replace("__PEND__", _json.dumps(pend, ensure_ascii=False))
            .replace("__G__", _json.dumps(_INDV2_GROUPS, ensure_ascii=False))
            .replace("__ASOF__", asof))


def _render_indicator_charts(data):
    """지표 탭 v2 — 사이클 위치 + 기능별 그룹 + 신호 배지/해석 + 신호강도순 토글.
    데이터는 엔진(06:30 수집) 가격지수 시계열을 그대로 쓰고, 미연결 항목은 '연결예정'으로 표시."""
    from datetime import date
    from math import ceil
    live = data is not _IND_SAMPLE
    ind, pend = _indicators_v2_payload(data)
    if not ind:
        st.caption("지표 데이터가 아직 없어요. 매일 06:30 수집 후 표시됩니다.")
        return
    asof = date.today().strftime("%Y-%m-%d")
    # 그룹 보기(가장 높은 레이아웃) 기준으로 높이 산정 — 클리핑 방지.
    rows = sum(ceil((sum(1 for m in ind if m["g"] == g)
                     + sum(1 for p in pend if p["g"] == g)) / 3)
               for g in ("lead", "coin", "supply", "fund"))
    height = 560 + 4 * 38 + rows * 186 + 40
    components.html(_indicator_chart_component(ind, pend, asof),
                    height=height, scrolling=False)
    src = ("KB·KOSIS·ECOS 실데이터" if live
           else "샘플(엔진 수집 전 — 06:30 자동 수집 후 실데이터로 교체)")
    st.caption("선행/동행/수급·심리/펀더멘털로 그룹핑 · 카드별 신호·해석(역행지표 자동 반전) · "
               f"사이클 위치는 선행·심리 종합 · {src}")


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
    """'+8.1%'·'-4.0%'·'+148%' → 절대 변동률(정렬·강조용)."""
    try:
        return abs(float(str(chg).replace("%", "").replace("+", "").strip()))
    except Exception:
        return 0.0


def _naver_land_url(apt):
    from urllib.parse import quote
    return "https://m.land.naver.com/search/result/" + quote(apt)


_WD_KR = ["월", "화", "수", "목", "금", "토", "일"]


def _anom_norm(rec):
    """특이거래 레코드를 14필드로 정규화(구 10/11/12필드 스냅샷 호환). 실패 시 None.
       (유형,배경,글자색,단지,지역,면적,가격,변동,거래유형,제외,거래일ISO|None,
        세대수|None, 빈도|None, 신호강도%|None)"""
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
            + (rec[13] if len(rec) >= 14 else None,))   # 신호강도%(sigstr)


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
    "느슨": {"freq": 5, "jump": 7.0, "margin": 0.3, "surge": 80, "days": 45},
    "표준": {"freq": 8, "jump": 10.0, "margin": 1.0, "surge": 150, "days": 30},
    "엄격": {"freq": 14, "jump": 13.0, "margin": 2.0, "surge": 200, "days": 21},
}


def _render_hot_complexes():
    """주목 단지 보드 — 거래 활발·상승(국토부 실거래) + 네이버 검색관심도(데이터랩)."""
    hot = [h for h in (fetch_hot_complexes() or []) if isinstance(h, dict)]
    if not hot:
        return
    st.markdown('<div class="re-grp">주목 단지<span class="sub">거래 활발·상승 + '
                '네이버 검색관심도</span></div>', unsafe_allow_html=True)
    has_search = any(isinstance(h.get("search"), (int, float)) for h in hot)
    body = ""
    for i, h in enumerate(hot[:12], 1):
        sd = "서울" if h.get("sd") == "seoul" else "경기"
        chg = h.get("chg") or 0
        chg_cls = "up" if chg >= 0 else "dn"
        vol = h.get("vol_chg") or 0
        vol_cls = "up" if vol >= 0 else "dn"
        sval = h.get("search")
        si = (f'<div class="re-hot-si"><span class="bar">'
              f'<i style="width:{max(0, min(100, int(sval)))}%"></i></span>'
              f'<span class="v">{int(sval)}</span></div>'
              if isinstance(sval, (int, float)) else '<div class="re-hot-si dim">–</div>')
        apt = h.get("apt", "")
        apt_link = (f'<a href="{_naver_land_url(apt)}" target="_blank" '
                    f'rel="noopener">{apt}</a>')
        body += (f'<div class="re-hot"><span class="re-hot-rk">{i}</span>'
                 f'<div style="flex:1"><div class="re-apt">{apt_link} '
                 f'<span class="re-sub">· {sd} {h.get("gu","")} · {h.get("area","")}</span></div>'
                 f'<div class="re-sub">최근 {h.get("recent",0)}건 '
                 f'<span class="{vol_cls}">({"+" if vol>=0 else ""}{vol}%)</span> · '
                 f'1년 {h.get("freq",0)}건</div></div>'
                 f'<div class="re-hot-r"><div class="re-price">{h.get("price_eok","-")}</div>'
                 f'<div class="re-chg {chg_cls}">{"+" if chg>=0 else ""}{chg}%</div></div>{si}</div>')
    st.markdown(f'<div class="re-hotwrap">{body}</div>', unsafe_allow_html=True)
    st.caption(("거래 활발·상승 단지 · 네이버 데이터랩 검색관심도(0~100, 상대값)"
                if has_search else
                "거래 활발·상승 단지 · 검색관심도는 네이버 키 연결 시 표시")
               + " · 호갱노노·아실 등 인기리스트는 공식 API 부재·약관으로 미사용 · "
               "단지명 클릭 시 네이버부동산.")


def _render_anomalies():
    from datetime import date as _date
    today = _date.today()
    typ_f = st.segmented_control(
        "유형", ["전체", "신고가", "신저가", "거래량 급증", "급등", "급락"],
        default="전체", key="re_anom_type")
    reg_f = st.segmented_control(
        "지역", ["수도권", "서울", "경기", "강남3구"],
        default="수도권", key="re_anom_region")
    sort_f = st.segmented_control(
        "정렬", ["최신순", "변동순", "금액순", "유형순"],
        default="최신순", key="re_anom_sort")
    sens_f = st.segmented_control(
        "민감도", ["느슨", "표준", "엄격"], default="표준", key="re_anom_sens",
        help="소형단지(거래빈도) 컷·신호강도·표시기간을 한 번에 조절 — 너무 많/적으면 바꿔보세요")
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
        typ, d, freq, sig = r[0], r[10], r[12], r[13]
        if isinstance(freq, (int, float)) and freq < P["freq"]:   # 소형/저유동 컷
            return False
        dt = _anom_date(d)                                        # 표시 기간 컷
        if dt and (today - dt).days > P["days"]:
            return False
        if isinstance(sig, (int, float)):                        # 유형별 신호강도 컷
            if typ in ("급등", "급락") and sig < P["jump"]:
                return False
            if typ in ("신고가", "신저가") and sig < P["margin"]:
                return False
            if typ == "거래량 급증" and sig < P["surge"]:
                return False
        return True

    anoms = [na for na in (_anom_norm(r) for r in fetch_anomalies()) if na]
    # 지역·직거래 → 민감도 프리셋(빈도·기간·신호강도) 순으로 좁힌다(유형 필터는 밴드 뒤)
    base_pool = [r for r in anoms
                 if not (r[9] and exclude_direct) and _pass_region(r[4])]
    pool = [r for r in base_pool if _pass_preset(r)]

    # 유형별 건수 밴드
    _order = ["신고가", "신저가", "거래량 급증", "급등", "급락"]
    _col = {"신고가": "#B65F5A", "신저가": "#5A7CA0", "거래량 급증": "#854F0B",
            "급등": "#B65F5A", "급락": "#5A7CA0"}
    cnt = {t: 0 for t in _order}
    for r in pool:
        if r[0] in cnt:
            cnt[r[0]] += 1
    chips = f'<span class="re-stat"><b>{len(pool)}</b>전체</span>' + "".join(
        f'<span class="re-stat"><b style="color:{_col[t]}">{cnt[t]}</b>{t}</span>'
        for t in _order)
    st.markdown(f'<div class="re-statband">{chips}</div>', unsafe_allow_html=True)

    # 상승압력 게이지: 신고가 vs 신저가 비율 (시장 방향 한눈에)
    up_n, dn_n = cnt["신고가"], cnt["신저가"]
    if up_n + dn_n:
        up_p = round(up_n / (up_n + dn_n) * 100)
        label = ("상승 우세" if up_p >= 60 else "하락 우세" if up_p <= 40 else "혼조")
        st.markdown(
            f'<div class="re-press"><span class="lab">상승압력 <b>{label}</b></span>'
            f'<span class="bar"><i style="width:{up_p}%"></i></span>'
            f'<span class="nums"><b style="color:#B65F5A">신고가 {up_n}</b> · '
            f'<b style="color:#5A7CA0">신저가 {dn_n}</b></span></div>',
            unsafe_allow_html=True)

    # 유형 필터 적용 → 표시 행
    rows = [r for r in pool
            if not (typ_f and typ_f != "전체" and r[0] != typ_f)]

    def _price_won(p):
        try:
            s = str(p).replace(",", "").strip()
            return float(s.replace("억", "").strip()) if "억" in s else -1.0
        except Exception:
            return -1.0

    if sort_f == "금액순":
        rows.sort(key=lambda r: _price_won(r[6]), reverse=True)
    elif sort_f == "유형순":
        oi = {t: i for i, t in enumerate(_order)}
        rows.sort(key=lambda r: (oi.get(r[0], 99), -_chg_abs(r[7])))
    elif sort_f == "최신순":
        rows.sort(key=lambda r: (r[10] is not None, r[10] or "", _chg_abs(r[7])),
                  reverse=True)
    else:
        rows.sort(key=lambda r: _chg_abs(r[7]), reverse=True)

    if not rows:
        st.caption("조건에 맞는 거래가 없어요. 필터를 바꿔보세요.")
        return

    grouped = (sort_f == "최신순")
    html = ""
    cur_day = None
    for typ, bg, fg, apt, gu, area, price, chg, trade, excl, d, units, freq, sig in rows:
        if grouped:
            dl = _anom_daylabel(d)
            if dl != cur_day:
                cur_day = dl
                html += f'<div class="re-daygroup">{dl}</div>'
        v = _chg_abs(chg)
        chg_cls = "dn" if str(chg).startswith("-") else "up"
        emph = "lv2" if v >= 7 else ("lv1" if v >= 3 else "")
        unit_s = (f" · {int(units):,}세대"
                  if isinstance(units, (int, float)) and units else "")
        freq_s = (f" · 1년 {int(freq)}건"
                  if isinstance(freq, (int, float)) and freq else "")
        trade_html = ('<span style="color:#A32D2D">직거래(증여추정·제외)</span>'
                      if trade == "직거래" else f"거래유형 {trade}")
        date_inline = ("" if grouped or not _anom_date(d)
                       else f"{_anom_daylabel(d)} · ")
        apt_link = (f'<a href="{_naver_land_url(apt)}" target="_blank" '
                    f'rel="noopener">{apt}</a>')
        html += (f'<div class="re-anom{" excl" if excl else ""}">'
                 f'<span class="re-bdg" style="background:{bg};color:{fg}">{typ}</span>'
                 f'<div style="flex:1"><div class="re-apt">{apt_link} '
                 f'<span class="re-sub">· {gu} · {area}{unit_s}{freq_s}</span></div>'
                 f'<div class="re-sub">{date_inline}{trade_html}</div></div>'
                 f'<div><div class="re-price">{price}</div>'
                 f'<div class="re-chg {chg_cls} {emph}">{chg}</div></div></div>')
    st.markdown(html, unsafe_allow_html=True)
    st.caption("소형·저유동 단지는 거래빈도 컷으로 제외(세대수 미의존) · 신고가=최근 1년 최고 "
               "초과 · 급등락=직전 동일면적 거래 대비 · 거래량 급증=최근 4주 vs 평균 · "
               "민감도로 양 조절 · 직거래(증여추정) 기본 제외 · 단지명 클릭 시 네이버부동산.")


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
            cards += (f'<a class="re-hl-card" href="{it["url"]}" target="_blank" rel="noopener">'
                      f'<span class="re-hl-dday">{it["dday"]}</span>'
                      f'<div class="re-hl-nm">{it["nm"]}</div>'
                      f'<div class="re-hl-meta">{reg_kr} {it["gu"]} · {it["typ"]} · {_units(it["nse"])}</div>'
                      f'<div class="re-hl-when">청약 {it["s"]}~{it["e"]} · 입주 {it["mv"]}</div>'
                      f'<span class="re-hl-go">↗</span></a>')
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
        html += (f'<a class="re-sub-card" href="{it["url"]}" target="_blank" rel="noopener">'
                 f'<span class="re-sub-bdg" style="background:{bg};color:{fg}">{it["dday"]}</span>'
                 f'<div style="flex:1"><div class="re-sub-nm">{it["nm"]}</div>'
                 f'<div class="re-sub-meta">{reg_kr} {it["gu"]} · {it["typ"]} · '
                 f'{_units(it["nse"])} · {it["addr"]}</div></div>'
                 f'<div class="re-sub-r"><b>청약 {it["s"]}~{it["e"]}</b>입주 {it["mv"]}</div>'
                 f'<span class="re-sub-go">↗</span></a>')
    st.markdown(html, unsafe_allow_html=True)
    if live:
        st.caption("소스: 한국부동산원 청약홈 분양정보(data.go.kr) — 실데이터. "
                   "카드를 누르면 청약홈 해당 공고로 이동해요. "
                   "D-day는 청약 시작일(예정)·마감일(진행 중) 기준 자동 계산. 진행/임박 우선.")
    else:
        st.caption("소스: 한국부동산원 청약홈 분양정보(data.go.kr) — 현재 샘플. "
                   "‘갱신’ 누르면 실데이터(청약홈 분양정보 활용신청 필요). "
                   "카드를 누르면 청약홈 공고 목록으로 이동(샘플이라 개별 공고 링크 없음). "
                   "D-day는 청약 시작·마감일 기준 자동 계산.")


def _run_collection():
    """뷰어 '최신 데이터 불러오기' — 라이브 API를 호출하지 않고 DB 스냅샷만 다시 읽는다.

    KB(data-api.kbland.kr)는 Streamlit Cloud IP에서 차단/타임아웃되고, 국토부 대량 호출도
    뷰어에서는 불안정하다(엔진-우선 원칙). 그래서 실제 수집은 매일 06:30 GitHub Actions가
    수행해 Supabase(realestate_snapshots)에 채우고, 뷰어는 그 최신 행을 읽기만 한다.
    이 함수는 스냅샷 캐시를 비워 '방금 06:30/수동 워크플로가 쓴 최신본'을 즉시 반영한다.
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


def _render_collect_controls():
    """지도 탭 상단 컨트롤 — 데이터 기준 캡션 + 갱신/진단 버튼 + 수집·진단 처리.
       (증시 '새로고침'과 같은 위치: 서브탭 제목 바로 아래.)"""
    asof = st.session_state.get("re_asof")
    if not asof:
        snap = _load_re_snapshot()
        asof = (snap or {}).get("asof") if snap else None
    if asof:
        st.caption(f"수도권 아파트 · KB 월간 매매지수·국토부 실거래 기준 {asof} KST · 매일 06:30 자동 갱신")
    else:
        st.caption("수도권 아파트 · 현재 샘플 — 매일 06:30 자동 수집(KB 가격지수·실거래) 후 "
                   "실데이터로 채워집니다.")

    _re_render_lock_gate()
    authed = _re_authed()
    col_a, col_b = st.columns([3, 1])
    with col_a:
        do_collect = st.button(
            "🔄 최신 데이터 불러오기", disabled=not authed,
            help="매일 06:30 GitHub Actions가 KB·국토부 데이터를 수집해 DB에 저장합니다. "
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
    # 증시와 동일하게 '메인탭 → 서브탭' 사이에 빈 블록이 끼지 않도록
    # st.tabs를 가장 먼저 만든다. 부동산 전용 CSS(_RE_CSS)는 별도 markdown
    # 블록으로 두면 그 블록이 세로 간격을 한 칸 더 먹어 증시보다 벌어지므로,
    # 첫 패널(지도)의 accent-bar와 한 블록으로 합쳐 주입한다(간격 일치).
    t_map, t_ind, t_anom, t_sub, t_kw = st.tabs(
        ["지도", "지표", "거래", "분양", "키워드"])

    with t_map:
        st.markdown(_RE_CSS + '<div class="accent-bar"></div>',
                    unsafe_allow_html=True)
        st.title("수도권 아파트 가격지도")
        _render_collect_controls()
        _render_map()

    with t_ind:
        st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
        st.title("부동산 시장 지표")
        st.caption("사이클 위치 · 선행/동행/수급·심리/펀더멘털 그룹 · 카드별 신호·해석 · "
                   "기능별/신호강도순 토글")
        _render_indicator_charts(_resolved_indicator_series())

    with t_anom:
        st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
        st.title("거래 동향")
        st.caption("주목 단지(거래 활발·상승 + 검색관심도) · 특이거래(신고가·급등락·거래량) · "
                   "국토부 실거래 기준 · 직거래(증여추정) 기본 제외")
        _render_hot_complexes()
        st.markdown('<div class="re-grp" style="margin-top:14px">특이거래'
                    '<span class="sub">신고가·신저가·급등락·거래량 급증</span></div>',
                    unsafe_allow_html=True)
        _render_anomalies()

    with t_sub:
        st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
        st.title("분양 단지")
        st.caption("한국부동산원 청약홈 분양정보 · 청약 임박·진행 우선 · 매일 06:30 자동 갱신")
        if _re_authed():
            if st.button(
                    "🔄 최신 분양정보 불러오기", key="re_sub_refresh",
                    help="매일 06:30 GitHub Actions가 청약홈 분양정보를 수집해 DB에 저장합니다. "
                         "이 버튼은 그 최신본을 즉시 다시 불러옵니다.",
                    use_container_width=True):
                with st.spinner("DB에서 최신 분양정보 불러오는 중..."):
                    _run_collection()
                st.success("최신 분양정보를 불러왔어요.")
                st.rerun()
        _render_subscriptions()

    with t_kw:
        # 키워드 뷰어가 자체적으로 accent-bar + 제목을 그린다(증시 키워드 탭과 동일).
        from modules.realestate_keywords_view import render_realestate_keywords
        render_realestate_keywords()
