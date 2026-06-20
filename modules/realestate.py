"""부동산 시장 모니터링 탭 — 지도 / 지표 / 거래.

수도권(서울 25개 자치구 + 경기 24개 시) 주간 매매·전세 등락, 거래량, 전세가율을
실제 비율 지도(choropleth)로 보여주고, 시장지표·특이거래를 함께 본다.
(경기 외곽 7개 시군 연천·포천·동두천·양주·가평·양평·여주는 제외. 서울·경기 경계는 굵은 선.)

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

import json

import streamlit as st
import streamlit.components.v1 as components

_VIEWBOX = "0 0 1100 1087"

# ── 수도권 행정경계(실제 비율) + 내장 샘플 수치 ──────────────────
#   n(정식명) sl(짧은라벨) sd(seoul|gg) d(SVG path) cx,cy(라벨좌표) ar(라벨우선순위 면적)
#   mm/js/v/vc/jr (주간 매매%/전세%/거래건/거래전주비%/전세가율%)
_GEO = json.loads(r"""[{"n":"광주시","sl":"광주","sd":"gg","d":"M770.4 478.8L788.4 461.8L824.8 465.8L840.6 490.3L847.9 516.4L833.0 534.6L875.6 599.9L900.1 602.2L899.5 629.5L846.5 667.2L836.3 665.5L801.9 696.6L800.6 713.4L782.0 709.2L746.1 715.1L742.0 676.1L747.7 642.0L730.1 644.5L695.5 629.1L676.1 655.8L660.2 640.2L612.7 650.6L607.4 647.5L605.1 629.5L623.3 624.6L643.6 584.7L662.3 566.9L664.3 548.0L650.1 519.9L683.2 511.3L703.3 518.1L724.0 504.4L719.0 491.3L770.4 478.8Z","cx":755.2,"cy":592.3,"ar":74724,"mm":0.03,"js":0.06,"v":30,"vc":22,"jr":62},{"n":"화성시","sl":"화성","sd":"gg","d":"M408.0 705.5L409.5 720.0L429.8 727.9L451.3 753.3L498.9 756.9L515.1 739.2L540.9 742.4L562.2 765.1L622.0 763.0L630.6 799.3L603.8 810.9L594.4 833.7L576.2 834.6L566.9 819.4L547.9 815.3L538.8 781.9L503.2 780.0L477.1 802.1L504.1 815.9L511.0 841.6L480.9 850.4L476.3 883.2L462.6 903.2L430.3 906.4L420.4 913.6L382.6 904.7L365.2 913.6L341.1 947.8L322.7 958.6L283.5 960.1L276.0 943.8L239.6 943.7L237.1 924.8L249.5 906.6L258.0 873.5L247.2 866.1L256.6 849.5L281.6 848.5L290.7 827.0L277.2 804.3L265.4 814.4L235.4 813.7L217.8 839.2L180.0 860.8L165.3 840.0L174.3 829.5L153.4 816.9L158.7 772.5L169.4 758.2L157.1 745.6L178.3 720.9L223.4 732.7L245.4 728.2L276.3 738.4L277.0 716.5L296.4 703.9L328.7 716.6L395.1 693.4L408.0 705.5Z","cx":397.3,"cy":823.2,"ar":127269,"mm":0.12,"js":-0.01,"v":63,"vc":-4,"jr":65},{"n":"김포시","sl":"김포","sd":"gg","d":"M176.5 279.1L163.6 326.0L291.1 395.1L280.4 416.5L232.6 405.3L215.0 406.6L189.7 382.3L150.0 362.7L130.2 372.4L122.0 392.4L69.4 410.6L27.7 348.4L22.0 325.9L26.1 300.5L17.8 291.4L24.9 267.2L14.0 239.6L52.7 237.7L63.8 250.1L104.6 253.0L132.7 228.7L159.5 222.9L176.5 279.1Z","cx":95.6,"cy":313.2,"ar":53647,"mm":-0.02,"js":0.11,"v":45,"vc":-3,"jr":57},{"n":"안성시","sl":"안성","sd":"gg","d":"M959.0 914.0L914.1 930.0L914.4 952.0L903.6 961.1L887.4 969.8L853.3 973.6L844.6 986.5L860.8 1002.4L838.5 1017.9L811.0 1016.9L772.3 1039.3L753.8 1072.9L735.1 1054.4L710.2 1050.4L687.4 1038.1L670.0 1017.3L615.0 998.8L591.3 1001.1L606.8 978.0L623.2 973.8L616.0 955.7L623.4 943.5L577.8 937.5L598.8 921.5L594.7 884.4L663.6 886.6L702.5 855.7L716.8 854.2L716.1 833.1L752.2 846.3L773.7 871.0L789.1 857.6L805.0 872.3L819.1 869.2L858.2 880.6L882.1 876.5L879.0 851.3L887.5 830.6L957.3 858.8L969.9 887.7L959.0 914.0Z","cx":767.6,"cy":947.7,"ar":95006,"mm":-0.0,"js":0.04,"v":22,"vc":-1,"jr":66},{"n":"이천시","sl":"이천","sd":"gg","d":"M899.5 629.5L926.3 626.6L944.5 644.9L967.4 647.7L998.7 683.9L982.1 710.1L990.1 736.2L978.8 742.1L984.3 780.7L971.1 795.3L980.0 806.1L1008.1 803.0L1027.3 791.1L1047.7 791.9L1086.0 837.0L1079.6 879.7L1050.7 890.0L1017.6 911.5L1004.8 929.3L983.8 918.3L944.9 921.2L959.0 914.0L969.9 887.7L957.3 858.8L870.8 823.6L872.5 806.4L842.2 797.2L838.2 785.0L809.7 776.5L792.0 760.1L801.9 696.6L836.3 665.5L846.5 667.2L899.5 629.5Z","cx":900.4,"cy":778.6,"ar":88994,"mm":0.01,"js":0.0,"v":36,"vc":-21,"jr":61},{"n":"파주시","sl":"파주","sd":"gg","d":"M287.3 24.9L290.7 45.1L321.5 50.9L324.8 35.4L340.3 30.5L355.0 44.8L377.5 44.8L380.2 19.9L417.3 34.7L448.2 14.0L469.8 14.0L491.9 24.6L426.4 113.0L426.1 144.2L414.8 164.0L395.1 168.9L386.8 214.5L416.5 232.7L410.2 257.2L390.2 258.7L383.9 276.4L365.9 284.6L340.3 270.5L300.0 281.1L282.2 271.5L261.9 299.1L214.9 299.3L183.0 312.9L168.6 303.4L176.5 279.1L154.9 217.5L166.1 178.5L153.0 171.0L182.8 144.0L164.0 125.3L169.4 114.8L158.1 92.5L165.2 59.7L181.9 70.8L204.7 74.5L233.5 63.1L229.1 43.3L251.2 31.5L267.6 33.6L287.3 24.9Z","cx":296.0,"cy":154.1,"ar":101297,"mm":-0.09,"js":-0.01,"v":26,"vc":-15,"jr":71},{"n":"용인시","sl":"용인","sd":"gg","d":"M792.0 760.1L809.7 776.5L838.2 785.0L842.2 797.2L872.5 806.4L870.8 823.6L887.5 830.6L879.0 851.3L882.1 876.5L858.2 880.6L819.1 869.2L805.0 872.3L789.1 857.6L773.7 871.0L752.2 846.3L716.1 833.1L716.8 854.2L702.5 855.7L663.6 886.6L594.7 884.4L581.4 850.7L603.8 810.9L630.6 799.3L622.0 763.0L562.2 765.1L540.9 742.4L558.1 726.7L539.4 712.5L562.2 697.6L563.1 686.8L535.1 688.5L535.4 676.8L515.4 664.9L509.2 642.6L495.2 636.1L503.9 616.4L588.8 653.4L660.2 640.2L676.1 655.8L695.5 629.1L730.1 644.5L747.7 642.0L742.0 676.1L746.1 715.1L782.0 709.2L800.6 713.4L792.0 760.1Z","cx":671.4,"cy":751.3,"ar":105999,"mm":0.31,"js":0.11,"v":116,"vc":27,"jr":52},{"n":"하남시","sl":"하남","sd":"gg","d":"M634.5 418.5L667.5 407.4L700.8 439.3L701.3 447.5L743.5 469.2L751.7 481.5L719.0 491.3L724.0 504.4L703.3 518.1L683.2 511.3L645.2 520.9L610.8 519.5L631.3 494.2L615.3 478.2L633.0 451.4L650.9 436.2L634.5 418.5Z","cx":676.7,"cy":460.3,"ar":15992,"mm":0.26,"js":0.26,"v":48,"vc":4,"jr":51},{"n":"의왕시","sl":"의왕","sd":"gg","d":"M517.1 574.9L519.0 585.8L495.2 636.1L459.1 659.9L443.2 682.7L413.3 682.4L410.9 678.5L426.5 662.5L460.6 589.2L490.0 576.7L517.1 574.9Z","cx":478.0,"cy":612.6,"ar":11653,"mm":0.05,"js":0.07,"v":23,"vc":2,"jr":58},{"n":"군포시","sl":"군포","sd":"gg","d":"M441.1 626.5L426.5 662.5L410.9 678.5L388.7 664.7L360.9 666.6L379.2 629.9L395.5 613.4L420.8 609.8L441.1 626.5Z","cx":402.1,"cy":646.2,"ar":5510,"mm":0.14,"js":0.0,"v":16,"vc":-11,"jr":59},{"n":"시흥시","sl":"시흥","sd":"gg","d":"M265.6 521.3L311.2 533.2L330.6 577.9L341.3 588.5L359.9 587.9L364.6 612.5L348.3 626.6L309.0 625.0L275.9 647.3L249.7 645.7L212.7 672.5L183.8 652.9L191.8 632.9L241.8 568.2L256.8 563.8L265.7 541.4L265.6 521.3Z","cx":289.6,"cy":600.5,"ar":27337,"mm":0.04,"js":0.01,"v":19,"vc":-4,"jr":59},{"n":"오산시","sl":"오산","sd":"gg","d":"M576.2 834.6L562.4 845.9L516.3 848.4L504.1 815.9L477.1 802.1L503.2 780.0L538.8 781.9L547.9 815.3L566.9 819.4L576.2 834.6Z","cx":518.0,"cy":808.7,"ar":6778,"mm":0.03,"js":0.06,"v":30,"vc":-10,"jr":60},{"n":"남양주시","sl":"남양주","sd":"gg","d":"M731.6 226.8L781.3 239.4L804.5 275.4L816.5 280.9L814.6 299.9L839.2 327.8L831.5 353.0L813.4 372.4L803.2 406.8L771.1 458.1L770.4 478.8L751.7 481.5L743.5 469.2L701.3 447.5L700.8 439.3L667.5 407.4L634.5 418.5L614.2 379.3L620.7 361.3L583.4 358.5L565.4 351.3L567.9 313.9L555.3 307.0L597.3 277.3L599.9 257.9L617.3 251.2L642.5 251.3L652.5 241.8L680.5 244.8L692.1 252.5L725.2 238.2L731.6 226.8Z","cx":702.7,"cy":355.7,"ar":72309,"mm":-0.02,"js":0.04,"v":56,"vc":18,"jr":64},{"n":"구리시","sl":"구리","sd":"gg","d":"M583.4 358.5L620.7 361.3L614.2 379.3L634.5 418.5L585.2 436.8L573.6 424.2L589.9 394.6L578.2 379.1L583.4 358.5Z","cx":605.8,"cy":406.6,"ar":4768,"mm":0.15,"js":0.06,"v":16,"vc":15,"jr":60},{"n":"과천시","sl":"과천","sd":"gg","d":"M466.4 534.4L512.3 535.8L522.6 560.4L517.1 574.9L490.0 576.7L460.6 589.2L440.4 565.3L442.1 550.7L466.4 534.4Z","cx":481.1,"cy":562.8,"ar":4505,"mm":0.31,"js":0.27,"v":42,"vc":34,"jr":58},{"n":"고양시","sl":"고양","sd":"gg","d":"M340.3 270.5L365.9 284.6L383.9 276.4L390.2 258.7L410.2 257.2L403.4 273.1L401.7 330.4L419.8 331.4L424.6 317.7L444.1 310.7L469.4 323.1L457.9 346.6L462.6 364.1L450.4 368.2L433.7 346.2L393.7 356.7L382.7 386.8L383.6 403.7L364.9 407.6L341.5 423.2L163.6 326.0L168.6 303.4L183.0 312.9L214.9 299.3L261.9 299.1L282.2 271.5L300.0 281.1L340.3 270.5Z","cx":324.4,"cy":338.8,"ar":50763,"mm":-0.03,"js":-0.02,"v":53,"vc":5,"jr":57},{"n":"안산시","sl":"안산","sd":"gg","d":"M67.1 704.5L92.5 721.1L103.9 720.6L117.1 745.8L143.5 756.4L140.2 770.4L81.4 761.1L65.5 776.6L42.5 774.7L39.9 756.7L57.8 740.4L60.2 727.1L46.5 704.4L64.7 703.1L75.5 689.1L103.2 676.7L67.1 704.5ZM364.6 612.5L379.2 629.9L360.9 666.6L388.7 664.7L410.9 678.5L408.0 705.5L395.1 693.4L328.7 716.6L302.0 687.2L260.2 695.4L215.4 683.1L212.7 672.5L249.7 645.7L275.9 647.3L309.0 625.0L348.3 626.6L364.6 612.5Z","cx":300.8,"cy":656.0,"ar":20633,"mm":0.16,"js":-0.02,"v":61,"vc":-13,"jr":66},{"n":"평택시","sl":"평택","sd":"gg","d":"M576.2 834.6L594.4 833.7L581.4 850.7L594.7 884.4L598.8 921.5L577.8 937.5L623.4 943.5L616.0 955.7L623.2 973.8L606.8 978.0L591.3 1001.1L585.5 997.7L547.8 1030.4L507.6 1040.0L472.9 1033.1L390.2 1062.3L386.1 1042.2L369.4 1032.6L347.7 1035.8L346.0 1020.4L330.6 1010.3L310.6 983.9L279.0 966.6L283.5 960.1L322.7 958.6L341.1 947.8L365.2 913.6L382.6 904.7L420.4 913.6L430.3 906.4L462.6 903.2L476.3 883.2L480.9 850.4L511.0 841.6L516.3 848.4L562.4 845.9L576.2 834.6Z","cx":476.4,"cy":951.7,"ar":78730,"mm":0.1,"js":-0.01,"v":57,"vc":7,"jr":56},{"n":"광명시","sl":"광명","sd":"gg","d":"M318.3 516.5L329.9 519.0L357.7 508.4L382.3 554.2L359.9 587.9L341.3 588.5L330.6 577.9L311.2 533.2L318.3 516.5Z","cx":346.2,"cy":543.7,"ar":5695,"mm":0.31,"js":0.26,"v":93,"vc":-3,"jr":55},{"n":"부천시","sl":"부천","sd":"gg","d":"M318.3 516.5L311.2 533.2L255.6 521.4L231.5 505.4L234.0 481.0L248.5 477.3L255.6 442.7L258.9 447.9L307.5 455.6L306.0 503.3L318.3 516.5Z","cx":269.6,"cy":492.1,"ar":7855,"mm":0.07,"js":0.06,"v":62,"vc":9,"jr":64},{"n":"안양시","sl":"안양","sd":"gg","d":"M442.1 550.7L440.4 565.3L460.6 589.2L441.1 626.5L420.8 609.8L395.5 613.4L379.2 629.9L364.6 612.5L359.9 587.9L382.3 554.2L409.3 541.9L427.6 552.7L442.1 550.7Z","cx":408.7,"cy":576.6,"ar":8862,"mm":0.1,"js":0.07,"v":51,"vc":36,"jr":49},{"n":"의정부시","sl":"의정부","sd":"gg","d":"M576.9 227.5L610.6 242.4L617.3 251.2L599.9 257.9L597.3 277.3L555.3 307.0L525.7 315.9L492.4 302.6L489.4 279.1L479.4 264.7L479.5 243.6L495.1 238.1L525.8 245.4L576.9 227.5Z","cx":541.0,"cy":271.0,"ar":12190,"mm":0.16,"js":0.1,"v":56,"vc":9,"jr":66},{"n":"성남시","sl":"성남","sd":"gg","d":"M623.3 624.6L605.1 629.5L607.4 647.5L588.8 653.4L503.9 616.4L519.0 585.8L522.6 560.4L540.0 562.2L561.6 546.2L569.2 531.2L610.8 519.5L650.1 519.9L664.3 548.0L662.3 566.9L643.6 584.7L623.3 624.6Z","cx":573.3,"cy":601.1,"ar":21478,"mm":0.31,"js":0.16,"v":99,"vc":30,"jr":49},{"n":"수원시","sl":"수원","sd":"gg","d":"M498.9 756.9L451.3 753.3L429.8 727.9L409.5 720.0L408.0 705.5L413.3 682.4L443.2 682.7L459.1 659.9L495.2 636.1L509.2 642.6L515.4 664.9L535.4 676.8L535.1 688.5L563.1 686.8L562.2 697.6L539.4 712.5L558.1 726.7L540.9 742.4L515.1 739.2L498.9 756.9Z","cx":486.7,"cy":693.1,"ar":18736,"mm":0.26,"js":0.17,"v":79,"vc":34,"jr":49},{"n":"강동구","sl":"강동","sd":"seoul","d":"M585.2 436.8L634.5 418.5L650.9 436.2L633.0 451.4L615.3 478.2L591.0 467.6L581.8 452.9L585.2 436.8Z","cx":612.7,"cy":444.1,"ar":4125,"mm":0.24,"js":0.18,"v":99,"vc":24,"jr":56},{"n":"송파구","sl":"송파","sd":"seoul","d":"M541.2 470.5L571.5 468.0L581.8 452.9L591.0 467.6L615.3 478.2L631.3 494.2L610.8 519.5L594.0 527.6L581.4 505.4L543.9 489.6L541.2 470.5Z","cx":589.2,"cy":491.9,"ar":6730,"mm":0.36,"js":0.09,"v":105,"vc":26,"jr":58},{"n":"강남구","sl":"강남","sd":"seoul","d":"M497.2 460.9L541.2 470.5L543.9 489.6L581.4 505.4L594.0 527.6L569.2 531.2L557.7 517.8L528.6 524.3L509.8 509.1L488.6 467.8L497.2 460.9Z","cx":533.2,"cy":497.5,"ar":7410,"mm":0.28,"js":0.09,"v":97,"vc":15,"jr":50},{"n":"서초구","sl":"서초","sd":"seoul","d":"M488.6 467.8L509.8 509.1L528.6 524.3L557.7 517.8L569.2 531.2L561.6 546.2L540.0 562.2L522.6 560.4L512.3 535.8L466.4 534.4L459.7 516.7L458.3 482.8L488.6 467.8Z","cx":487.0,"cy":512.9,"ar":10469,"mm":0.13,"js":0.24,"v":128,"vc":36,"jr":48},{"n":"관악구","sl":"관악","sd":"seoul","d":"M459.7 516.7L466.4 534.4L442.1 550.7L427.6 552.7L395.9 534.8L381.3 513.2L384.9 508.7L426.8 500.1L449.1 517.9L459.7 516.7Z","cx":426.7,"cy":526.1,"ar":4476,"mm":-0.02,"js":-0.02,"v":38,"vc":-2,"jr":71},{"n":"동작구","sl":"동작","sd":"seoul","d":"M458.3 482.8L459.7 516.7L449.1 517.9L426.8 500.1L384.9 508.7L400.6 496.6L406.7 479.0L429.9 475.3L458.3 482.8Z","cx":430.8,"cy":489.7,"ar":3186,"mm":0.08,"js":-0.01,"v":15,"vc":18,"jr":56},{"n":"영등포구","sl":"영등포","sd":"seoul","d":"M372.1 446.5L423.4 466.3L429.9 475.3L406.7 479.0L400.6 496.6L384.9 508.7L376.0 487.3L362.3 478.4L372.1 446.5Z","cx":391.5,"cy":476.8,"ar":4205,"mm":0.12,"js":0.09,"v":70,"vc":34,"jr":48},{"n":"금천구","sl":"금천","sd":"seoul","d":"M381.3 513.2L395.9 534.8L409.3 541.9L382.3 554.2L357.7 508.4L381.3 513.2Z","cx":377.3,"cy":524.0,"ar":2363,"mm":0.0,"js":-0.03,"v":22,"vc":-6,"jr":63},{"n":"구로구","sl":"구로","sd":"seoul","d":"M310.1 486.5L362.3 478.4L376.0 487.3L384.9 508.7L381.3 513.2L357.7 508.4L329.9 519.0L318.3 516.5L306.0 503.3L310.1 486.5Z","cx":343.6,"cy":495.3,"ar":3203,"mm":-0.02,"js":-0.01,"v":15,"vc":-8,"jr":70},{"n":"강서구","sl":"강서","sd":"seoul","d":"M280.4 416.5L291.1 395.1L305.9 407.7L341.5 423.2L372.1 446.5L368.6 452.8L347.8 445.4L347.5 466.0L325.0 469.1L307.5 455.6L258.9 447.9L255.6 442.7L280.4 416.5Z","cx":309.6,"cy":432.9,"ar":8621,"mm":0.01,"js":0.12,"v":24,"vc":1,"jr":60},{"n":"양천구","sl":"양천","sd":"seoul","d":"M307.5 455.6L325.0 469.1L347.5 466.0L347.8 445.4L368.6 452.8L362.3 478.4L310.1 486.5L307.5 455.6Z","cx":357.1,"cy":460.8,"ar":2511,"mm":0.33,"js":0.17,"v":43,"vc":0,"jr":57},{"n":"마포구","sl":"마포","sd":"seoul","d":"M364.9 407.6L417.0 441.8L440.5 438.2L441.4 445.3L423.4 466.3L372.1 446.5L341.5 423.2L364.9 407.6Z","cx":375.7,"cy":430.7,"ar":5864,"mm":0.33,"js":0.14,"v":77,"vc":20,"jr":49},{"n":"서대문구","sl":"서대문","sd":"seoul","d":"M429.9 391.5L433.0 419.1L445.4 431.5L440.5 438.2L417.0 441.8L384.8 421.0L429.9 391.5Z","cx":420.1,"cy":405.3,"ar":3048,"mm":0.15,"js":0.1,"v":14,"vc":-2,"jr":58},{"n":"은평구","sl":"은평","sd":"seoul","d":"M450.4 368.2L431.6 375.3L429.9 391.5L384.8 421.0L364.9 407.6L383.6 403.7L382.7 386.8L393.7 356.7L433.7 346.2L450.4 368.2Z","cx":407.9,"cy":381.0,"ar":6395,"mm":0.14,"js":-0.02,"v":62,"vc":10,"jr":61},{"n":"노원구","sl":"노원","sd":"seoul","d":"M555.3 307.0L567.9 313.9L565.4 351.3L583.4 358.5L578.2 379.1L545.4 384.1L516.9 369.1L530.6 355.1L525.7 315.9L555.3 307.0Z","cx":547.3,"cy":333.6,"ar":5127,"mm":-0.03,"js":0.06,"v":48,"vc":6,"jr":56},{"n":"도봉구","sl":"도봉","sd":"seoul","d":"M525.7 315.9L530.6 355.1L516.9 369.1L489.3 349.1L495.0 332.2L485.2 318.2L492.4 302.6L525.7 315.9Z","cx":510.5,"cy":340.7,"ar":3019,"mm":-0.06,"js":-0.07,"v":36,"vc":2,"jr":61},{"n":"강북구","sl":"강북","sd":"seoul","d":"M469.4 323.1L485.2 318.2L495.0 332.2L489.3 349.1L525.0 375.7L512.4 387.0L487.5 383.3L462.6 364.1L457.9 346.6L469.4 323.1Z","cx":480.0,"cy":356.6,"ar":4616,"mm":-0.08,"js":0.01,"v":10,"vc":-21,"jr":67},{"n":"성북구","sl":"성북","sd":"seoul","d":"M453.5 369.0L462.6 364.1L487.5 383.3L512.4 387.0L525.0 375.7L545.4 384.1L545.7 392.5L516.0 403.6L499.4 419.9L469.1 407.2L464.6 385.0L453.5 369.0Z","cx":505.6,"cy":389.8,"ar":5145,"mm":0.12,"js":-0.0,"v":38,"vc":13,"jr":63},{"n":"중랑구","sl":"중랑","sd":"seoul","d":"M545.4 384.1L578.2 379.1L589.9 394.6L573.6 424.2L552.3 425.8L545.4 384.1Z","cx":565.7,"cy":409.4,"ar":2078,"mm":-0.08,"js":0.02,"v":18,"vc":-9,"jr":70},{"n":"동대문구","sl":"동대문","sd":"seoul","d":"M499.4 419.9L516.0 403.6L545.7 392.5L552.3 425.8L546.1 437.1L523.0 427.2L499.6 425.9L499.4 419.9Z","cx":528.6,"cy":411.7,"ar":2359,"mm":0.03,"js":0.03,"v":41,"vc":-15,"jr":59},{"n":"광진구","sl":"광진","sd":"seoul","d":"M552.3 425.8L573.6 424.2L585.2 436.8L581.8 452.9L571.5 468.0L541.2 470.5L531.3 466.6L552.3 425.8Z","cx":563.0,"cy":444.9,"ar":2496,"mm":0.36,"js":0.27,"v":115,"vc":15,"jr":48},{"n":"성동구","sl":"성동","sd":"seoul","d":"M499.6 425.9L523.0 427.2L546.1 437.1L531.3 466.6L497.2 460.9L485.5 452.4L499.6 425.9Z","cx":515.9,"cy":444.8,"ar":2466,"mm":0.16,"js":0.14,"v":117,"vc":37,"jr":57},{"n":"용산구","sl":"용산","sd":"seoul","d":"M463.4 443.1L497.2 460.9L458.3 482.8L429.9 475.3L423.4 466.3L441.4 445.3L463.4 443.1Z","cx":459.1,"cy":463.6,"ar":2930,"mm":0.13,"js":0.28,"v":67,"vc":24,"jr":52},{"n":"중구","sl":"중","sd":"seoul","d":"M499.6 425.9L485.5 452.4L463.4 443.1L441.4 445.3L445.4 431.5L499.6 425.9Z","cx":468.6,"cy":437.3,"ar":1542,"mm":-0.05,"js":0.06,"v":51,"vc":9,"jr":56},{"n":"종로구","sl":"종로","sd":"seoul","d":"M450.4 368.2L464.6 385.0L469.1 407.2L499.4 419.9L499.6 425.9L445.4 431.5L433.0 419.1L431.6 375.3L450.4 368.2Z","cx":449.5,"cy":396.1,"ar":4304,"mm":-0.03,"js":0.0,"v":45,"vc":-15,"jr":64}]""")

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


def _kb_value_series(df, decimals=1):
    """KB Kbland 결과 df → 최근 7개 값 시리즈(날짜 정렬·값 컬럼 자동탐색). 실패 시 None."""
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
    return [round(v, decimals) for v in vals[-7:]] if len(vals) >= 2 else None


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


# (유형, 배경, 글자색, 단지, 지역, 면적, 가격, 변동, 거래유형, 제외여부)
_SAMPLE_ANOMALIES = [
    ("신고가", "#FCEBEB", "#A32D2D", "래미안원베일리", "서초구", "84㎡", "58.0억", "+3.2%", "중개", False),
    ("신고가", "#FCEBEB", "#A32D2D", "힐스테이트판교엘포레", "성남시", "84㎡", "24.5억", "+2.6%", "중개", False),
    ("거래량 급증", "#FAEEDA", "#854F0B", "파크리오", "송파구", "전체", "31건/주", "+148%", "-", False),
    ("급등", "#FCEBEB", "#A32D2D", "광교중흥S클래스", "수원시", "84㎡", "17.8억", "+8.1%", "중개", False),
    ("신저가", "#E6F1FB", "#0C447C", "상계주공7", "노원구", "59㎡", "6.1억", "-4.0%", "중개", False),
    ("급락", "#E6F1FB", "#0C447C", "은마", "강남구", "84㎡", "26.0억", "-7.5%", "직거래", True),
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


def _sub_status(start, end):
    """'MM.DD' 청약 기간으로 예정/분양중/마감 분류 (KST 기준). (라벨, 정렬순).
       연말연초 경계에서 창이 과도하게 과거/미래면 연도 이월로 간주해 보정."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    try:
        y = today.year
        s = datetime.strptime(f"{y}.{start}", "%Y.%m.%d").date()
        e = datetime.strptime(f"{y}.{end}", "%Y.%m.%d").date()
    except Exception:
        return "예정", 1
    try:
        if e < today - timedelta(days=300):       # 사실상 내년 건(연초)
            s = s.replace(year=s.year + 1)
            e = e.replace(year=e.year + 1)
        elif s > today + timedelta(days=300):     # 사실상 작년 건(연말)
            s = s.replace(year=s.year - 1)
            e = e.replace(year=e.year - 1)
    except ValueError:
        pass
    if today < s:
        return "예정", 1
    if s <= today <= e:
        return "분양중", 0
    return "마감", 2


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
  border-radius:12px;padding:11px 14px;margin-bottom:8px;transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease;}
.re-sub-card:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(52,53,47,.07);border-color:var(--sage,#A7BBA9);}
.re-sub-bdg{font-size:10.5px;font-weight:700;padding:2px 9px;border-radius:6px;flex:none;margin-top:1px;}
.re-sub-nm{font-weight:700;color:var(--ink,#34352f);}
.re-sub-meta{font-size:12px;color:var(--muted,#9a9b92);margin-top:2px;}
.re-sub-r{margin-left:auto;text-align:right;font-size:11.5px;color:var(--muted,#9a9b92);white-space:nowrap;padding-left:10px;}
.re-sub-r b{display:block;color:var(--ink,#34352f);font-size:12.5px;margin-bottom:1px;}
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
def _map_component(regions):
    d_json = json.dumps(regions, ensure_ascii=False, separators=(",", ":"))
    border_json = json.dumps(_BORDER)
    return (_MAP_HEAD.replace("__VIEWBOX__", _VIEWBOX)
            + "const D=" + d_json + ";\nconst BORDER=" + border_json + ";"
            + _MAP_SCRIPT)


_MAP_HEAD = """
<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{--ink:#34352f;--muted:#9a9b92;--card:#fff;--line:#ECEDE7;--line2:#DEDED7;--sage:#7E9A83;--up:#B65F5A;--dn:#5A7CA0;
  --kfont:'Pretendard',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;}
*{box-sizing:border-box}
body{margin:0;background:transparent;color:var(--ink);
  font-family:var(--kfont);font-size:14px;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;}
.strip{display:flex;gap:22px;align-items:center;overflow-x:auto;padding:6px 0 10px;border-bottom:1px solid var(--line);margin-bottom:12px}
.si{display:flex;align-items:center;gap:8px;white-space:nowrap}.si .lab{color:var(--muted);font-size:12px}.si .val{font-weight:700;font-size:13px}
table.sm{width:100%;border-collapse:collapse;font-size:12.5px;table-layout:fixed;margin-bottom:12px}
table.sm th,table.sm td{padding:7px 8px;text-align:right;border-bottom:1px solid var(--line)}
table.sm th{color:var(--muted);font-weight:400;font-size:11px}
table.sm td:first-child,table.sm th:first-child{text-align:left}
.up{color:var(--up)}.dn{color:var(--dn)}
.seg{display:inline-flex;border:1px solid var(--line2);border-radius:8px;overflow:hidden;margin:0 8px 12px 0;background:var(--card)}
.seg button{border:none;background:none;padding:6px 13px;font-size:12.5px;color:var(--muted);cursor:pointer;border-right:1px solid var(--line);font-family:var(--kfont)}
.seg button:last-child{border-right:none}.seg button.on{background:#EEF1EC;color:var(--ink);font-weight:700}
.mapwrap{position:relative;width:100%;max-width:940px;margin:0 auto;border:1px solid var(--line);border-radius:12px;background:#FCFCFA;overflow:hidden}
#map{display:block;width:100%}
.dist{stroke:#FCFCFA;stroke-width:0.7;cursor:pointer;transition:fill .45s ease,opacity .25s ease}
.dlabel{pointer-events:none;fill:#2f302a;font-family:var(--kfont)}
#hoverLabel{pointer-events:none;font-family:var(--kfont);font-weight:800;fill:#23241d;opacity:0;transition:opacity .12s ease}
#border{fill:none;stroke:#6E7A6A;stroke-width:2.2;stroke-linejoin:round;pointer-events:none}
.tip{position:absolute;pointer-events:none;background:var(--card);border:1px solid var(--line2);border-radius:8px;padding:9px 11px;font-size:12px;min-width:150px;box-shadow:0 6px 22px rgba(52,53,47,.13);opacity:0;transform:translateY(4px);transition:opacity .15s,transform .15s;z-index:5}
.ov{position:absolute;background:rgba(255,255,255,.93);border:1px solid var(--line);border-radius:8px;padding:9px 11px;font-size:11.5px}
.ov-leg{left:14px;bottom:14px}.ov-mov{right:14px;top:14px;min-width:120px}
.ovt{color:var(--muted);font-size:11px;margin-bottom:5px}
.note{color:var(--muted);font-size:11.5px;margin-top:9px}
</style></head><body>
<div class="strip" id="strip"></div>
<table class="sm"><thead><tr><th>권역</th><th>매매(주간)</th><th>전세(주간)</th><th>거래(주간)</th><th>전세가율</th></tr></thead><tbody id="regBody"></tbody></table>
<div>
  <div class="seg" id="regionSeg"><button data-r="all" class="on">수도권</button><button data-r="seoul">서울</button><button data-r="gg">경기</button></div>
  <div class="seg" id="metricSeg"><button data-m="mm" class="on">매매 등락</button><button data-m="js">전세 등락</button><button data-m="v">거래량</button><button data-m="jr">전세가율</button></div>
</div>
<div class="mapwrap" id="mapwrap">
  <svg id="map" viewBox="__VIEWBOX__" role="img" aria-label="수도권 시군구 주간 지표 지도"></svg>
  <div class="ov ov-leg"><div class="ovt" id="legTitle">주간 등락률</div><div id="legend"></div></div>
  <div class="ov ov-mov"><div class="ovt" id="moverTitle">매매 상승</div><div id="movers"></div></div>
  <div class="tip" id="tip"></div>
</div>
<div class="note">지역에 커서를 올리면 상세가 뜹니다 · 굵은 선 = 서울·경기 경계 · 빨강=상승, 파랑=하락 · 서울25+경기24</div>
<script>
"""

_MAP_SCRIPT = r"""
const fmt=v=>(v>0?"+":"")+v.toFixed(2)+"%";
const cls=v=>v>0.005?"up":(v<-0.005?"dn":"");
function colMM(v){if(v>=0.25)return"#CE8079";if(v>=0.12)return"#DEA39D";if(v>=0.03)return"#EDC8C3";if(v>-0.03)return"#EFEEE9";if(v>-0.10)return"#C6D4E4";return"#A9C0DA";}
function colV(v){if(v>=90)return"#7FC4AC";if(v>=60)return"#A6D6C4";if(v>=40)return"#C5E4D8";if(v>=25)return"#DCEFE8";return"#EDF5F1";}
function colJR(v){if(v>=70)return"#9FB6D2";if(v>=65)return"#B4C7DD";if(v>=60)return"#C8D6E7";if(v>=55)return"#DBE4F0";return"#EAF0F7";}
const legMM=[["+0.25%+","#CE8079"],["+0.12~","#DEA39D"],["+0.03~","#EDC8C3"],["\u00b10.03%","#EFEEE9"],["-0.03~","#C6D4E4"],["-0.10%-","#A9C0DA"]];
const legV=[["90건+","#7FC4AC"],["60~90","#A6D6C4"],["40~60","#C5E4D8"],["25~40","#DCEFE8"],["~25","#EDF5F1"]];
const legJR=[["70%+","#9FB6D2"],["65~70","#B4C7DD"],["60~65","#C8D6E7"],["55~60","#DBE4F0"],["~55","#EAF0F7"]];
let metric="mm",region="all";
function fill(d){return metric==="v"?colV(d.v):metric==="jr"?colJR(d.jr):colMM(d[metric]);}
function avg(a,k){return a.reduce((s,d)=>s+d[k],0)/a.length;}
function sum(a,k){return a.reduce((s,d)=>s+d[k],0);}
const seoul=D.filter(d=>d.sd==="seoul"),gg=D.filter(d=>d.sd==="gg");
const gn3=D.filter(d=>["강남구","서초구","송파구"].includes(d.n));
function strip(){const items=[["서울 매매",fmt(avg(seoul,"mm")),cls(avg(seoul,"mm")),[44,45,47,48,49,50,52]],["경기 매매",fmt(avg(gg,"mm")),cls(avg(gg,"mm")),[40,41,40,42,43,44,45]],["서울 전세",fmt(avg(seoul,"js")),cls(avg(seoul,"js")),[38,39,40,41,42,43,44]],["전세가율(서울)",avg(seoul,"jr").toFixed(1)+"%","",[57,56,56,55,55,54.9,54.8]],["매수우위지수","58.4","",[44,46,49,52,55,57,58]],["낙찰가율(서울)","94.2%","up",[88,89,90,91,92,93,94]]];
  document.getElementById("strip").innerHTML=items.map(([l,v,c,s])=>`<div class="si">${spark(s,c==="up"?"#B65F5A":c==="dn"?"#5A7CA0":"#7E9A83",54,20)}<span class="lab">${l}</span><span class="val ${c}">${v}</span></div>`).join("");}
function regTable(){const g=[["수도권",D],["서울",seoul],["경기",gg],["강남3구(강남·서초·송파)",gn3]];
  document.getElementById("regBody").innerHTML=g.map(([n,a])=>{const m=avg(a,"mm"),j=avg(a,"js"),v=sum(a,"v"),jr=avg(a,"jr");
    return `<tr><td>${n}</td><td class="${cls(m)}">${fmt(m)}</td><td class="${cls(j)}">${fmt(j)}</td><td>${v.toLocaleString()}건</td><td>${jr.toFixed(1)}%</td></tr>`;}).join("");}
function placeLabels(){const cand=D.filter(d=>!(region!=="all"&&d.sd!==region));
  cand.sort((a,b)=>{if(a.sd!==b.sd)return a.sd==="seoul"?-1:1;return b.ar-a.ar;});
  const placed=[],out=[];
  for(const d of cand){const fs=d.sd==="seoul"?9:11;const w=d.sl.length*fs*0.64,h=fs;
    if(d.sd==="gg"&&d.ar<420)continue;
    const box=[d.cx-w/2,d.cy-h/2,d.cx+w/2,d.cy+h/2];let ok=true;
    for(const p of placed){if(!(box[2]<p[0]||box[0]>p[2]||box[3]<p[1]||box[1]>p[3])){ok=false;break;}}
    if(!ok)continue;placed.push(box);
    out.push(`<text class="dlabel" x="${d.cx}" y="${d.cy}" text-anchor="middle" dominant-baseline="middle" font-size="${fs}" font-weight="${d.sd==="seoul"?700:600}" paint-order="stroke" stroke="#FCFCFA" stroke-width="2.8" stroke-linejoin="round">${d.sl}</text>`);}
  return out.join("");}
function drawMap(){const ps=D.map((d,i)=>{const dim=region!=="all"&&d.sd!==region;
    return `<path class="dist" data-i="${i}" d="${d.d}" fill="${fill(d)}" style="opacity:${dim?0.12:1};pointer-events:${dim?"none":"auto"}"></path>`;}).join("");
  document.getElementById("map").innerHTML=`<g id="paths">${ps}</g><path id="border" d="${BORDER}"></path><g id="labels">${placeLabels()}</g>`
    +`<text id="hoverLabel" text-anchor="middle" dominant-baseline="middle" paint-order="stroke" stroke="#FCFCFA" stroke-width="3.6" stroke-linejoin="round"></text>`;
  const wrap=document.getElementById("mapwrap"),tip=document.getElementById("tip"),pg=document.getElementById("paths"),hl=document.getElementById("hoverLabel");
  document.querySelectorAll("#map path.dist").forEach(p=>{
    p.onmouseenter=()=>{const d=D[+p.dataset.i];showTip(d);p.style.stroke="#34352f";p.style.strokeWidth="1.6";pg.appendChild(p);tip.style.opacity="1";tip.style.transform="translateY(0)";
      hl.setAttribute("x",d.cx);hl.setAttribute("y",d.cy);hl.setAttribute("font-size",d.sd==="seoul"?13:15);hl.textContent=d.sl;hl.style.opacity="1";};
    p.onmouseleave=()=>{p.style.stroke="#FCFCFA";p.style.strokeWidth="0.7";tip.style.opacity="0";tip.style.transform="translateY(4px)";hl.style.opacity="0";};});
  wrap.onmousemove=e=>{const r=wrap.getBoundingClientRect();let x=e.clientX-r.left+14,y=e.clientY-r.top+14;if(x>r.width-170)x=e.clientX-r.left-164;tip.style.left=x+"px";tip.style.top=y+"px";};}
function showTip(d){document.getElementById("tip").innerHTML=`<div style="font-weight:700;margin-bottom:5px">${d.n} <span style="font-weight:400;color:#9a9b92">${d.sd==="seoul"?"서울":"경기"}</span></div>
  <div style="color:#9a9b92">매매 <span class="${cls(d.mm)}">${fmt(d.mm)}</span> · 전세 <span class="${cls(d.js)}">${fmt(d.js)}</span></div>
  <div style="color:#9a9b92">거래 ${d.v}건 <span class="${cls(d.vc)}">(${d.vc>0?"+":""}${d.vc}%)</span></div>
  <div style="color:#9a9b92">전세가율 ${d.jr}%</div>`;}
function drawLegend(){const L=metric==="v"?legV:metric==="jr"?legJR:legMM;
  document.getElementById("legTitle").textContent=metric==="jr"?"전세가율":metric==="v"?"주간 거래건수":"주간 등락률";
  document.getElementById("legend").innerHTML=L.map(([t,c])=>`<div style="display:flex;align-items:center;gap:6px;margin:3px 0"><span style="width:12px;height:12px;border-radius:3px;background:${c};display:inline-block"></span>${t}</div>`).join("");}
function drawMovers(){const pool=region==="all"?D:D.filter(d=>d.sd===region);const k=metric==="v"?"v":metric;const top=[...pool].sort((a,b)=>b[k]-a[k]).slice(0,6);
  document.getElementById("moverTitle").textContent=metric==="v"?"거래 상위":metric==="jr"?"전세가율 상위":metric==="js"?"전세 상승":"매매 상승";
  document.getElementById("movers").innerHTML=top.map(d=>{const vv=metric==="v"?d.v+"건":metric==="jr"?d.jr+"%":fmt(d[metric]);
    return `<div style="display:flex;justify-content:space-between;gap:10px;margin:3px 0"><span>${d.sl}</span><span class="${(metric==="v"||metric==="jr")?"":cls(d[metric])}">${vv}</span></div>`;}).join("");}
function refresh(){drawMap();drawLegend();drawMovers();}
function spark(series,col,w,h){w=w||60;h=h||22;const mn=Math.min(...series),mx=Math.max(...series),r=mx-mn||1;
  const pts=series.map((v,i)=>`${(i/(series.length-1)*w).toFixed(1)},${(h-3-(v-mn)/r*(h-6)).toFixed(1)}`).join(" ");
  return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.6"/></svg>`;}
document.querySelectorAll("#metricSeg button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#metricSeg button").forEach(x=>x.classList.remove("on"));b.classList.add("on");metric=b.dataset.m;refresh();});
document.querySelectorAll("#regionSeg button").forEach(b=>b.onclick=()=>{document.querySelectorAll("#regionSeg button").forEach(x=>x.classList.remove("on"));b.classList.add("on");region=b.dataset.r;refresh();});
strip();regTable();refresh();
</script></body></html>
"""


# ── 서브탭 렌더러 ───────────────────────────────────────────────
def _render_map():
    components.html(_map_component(_merged_regions()), height=1320, scrolling=False)


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


def _render_indicators():
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


def _render_anomalies():
    typ_f = st.segmented_control(
        "유형", ["전체", "신고가", "신저가", "거래량 급증", "급등", "급락"],
        default="전체", key="re_anom_type")
    reg_f = st.segmented_control(
        "지역", ["수도권", "서울", "경기", "강남3구"],
        default="수도권", key="re_anom_region")
    exclude_direct = st.checkbox("직거래(증여추정) 제외", value=True, key="re_excl_direct")

    rows = []
    for typ, bg, fg, apt, gu, area, price, chg, trade, excl in fetch_anomalies():
        if excl and exclude_direct:
            continue
        if typ_f and typ_f != "전체" and typ != typ_f:
            continue
        if reg_f == "서울" and _region_of(gu) != "seoul":
            continue
        if reg_f == "경기" and _region_of(gu) != "gg":
            continue
        if reg_f == "강남3구" and not any(n in gu for n in _GANGNAM3):
            continue
        rows.append((typ, bg, fg, apt, gu, area, price, chg, trade, excl))

    rows.sort(key=lambda r: _chg_abs(r[7]), reverse=True)

    if not rows:
        st.caption("조건에 맞는 거래가 없어요. 필터를 바꿔보세요.")
        return

    html = ""
    for typ, bg, fg, apt, gu, area, price, chg, trade, excl in rows:
        v = _chg_abs(chg)
        chg_cls = "dn" if str(chg).startswith("-") else "up"
        emph = "lv2" if v >= 7 else ("lv1" if v >= 3 else "")
        trade_html = ('<span style="color:#A32D2D">직거래(증여추정·제외)</span>'
                      if trade == "직거래" else f"거래유형 {trade}")
        apt_link = (f'<a href="{_naver_land_url(apt)}" target="_blank" '
                    f'rel="noopener">{apt}</a>')
        html += (f'<div class="re-anom{" excl" if excl else ""}">'
                 f'<span class="re-bdg" style="background:{bg};color:{fg}">{typ}</span>'
                 f'<div style="flex:1"><div class="re-apt">{apt_link} '
                 f'<span class="re-sub">· {gu} · {area}</span></div>'
                 f'<div class="re-sub">{trade_html}</div></div>'
                 f'<div><div class="re-price">{price}</div>'
                 f'<div class="re-chg {chg_cls} {emph}">{chg}</div></div></div>')
    st.markdown(html, unsafe_allow_html=True)
    st.caption("신고가/신저가·거래량 급변·급등락. 직거래는 증여 추정으로 기본 제외 "
               "(국토부 실거래 '거래유형' 기준). 변동률 큰 순 정렬 · 단지명 클릭 시 네이버부동산. "
               "신고가 판정은 실거래 이력 누적 후 정확해져요.")


# ── 메인 ────────────────────────────────────────────────────────
def _render_subscriptions():
    region = st.segmented_control(
        "지역", ["수도권", "서울", "경기"], default="수도권",
        key="re_sub_region", label_visibility="collapsed")
    rmap = {"서울": "seoul", "경기": "gg"}
    subs = fetch_subscriptions()
    live = subs is not _SAMPLE_SUBS
    items = []
    for row in subs:
        try:
            nm, gu, addr, typ, nse, s, e, mv, sd = row
        except (ValueError, TypeError):
            continue
        if region in rmap and sd != rmap[region]:
            continue
        status, order = _sub_status(s, e)
        items.append((order, s, nm, gu, addr, typ, nse, e, mv, sd, status))
    items.sort(key=lambda x: (x[0], x[1]))
    if not items:
        st.caption("해당 지역 분양 단지가 없어요.")
        return
    bdg = {"분양중": ("#FCEBEB", "#A32D2D"), "예정": ("#EAF1EA", "#3F6F49"),
           "마감": ("#F0F1EC", "#8A8C82")}
    html = ""
    for order, s, nm, gu, addr, typ, nse, e, mv, sd, status in items:
        bg, fg = bdg[status]
        reg_kr = "서울" if sd == "seoul" else "경기"
        try:
            units = f"{int(nse):,}세대"
        except (ValueError, TypeError):
            units = "-세대"
        html += (f'<div class="re-sub-card">'
                 f'<span class="re-sub-bdg" style="background:{bg};color:{fg}">{status}</span>'
                 f'<div style="flex:1"><div class="re-sub-nm">{nm}</div>'
                 f'<div class="re-sub-meta">{reg_kr} {gu} · {typ} · {units} · {addr}</div></div>'
                 f'<div class="re-sub-r"><b>청약 {s}~{e}</b>입주 {mv}</div></div>')
    st.markdown(html, unsafe_allow_html=True)
    if live:
        st.caption("소스: 한국부동산원 청약홈 분양정보(data.go.kr) — 실데이터. "
                   "서울·경기 · 청약종료 임박/진행 우선. 상태는 청약기간 기준 자동 분류.")
    else:
        st.caption("소스: 한국부동산원 청약홈 분양정보(data.go.kr) — 현재 샘플. "
                   "‘갱신’ 누르면 실데이터(청약홈 분양정보 활용신청 필요). "
                   "상태는 청약기간 기준 자동 분류.")


def _run_collection():
    """국토부 실거래·청약홈 분양 수집 → 세션 저장 + (가능하면) Supabase 스냅샷 저장."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from engine.realestate_collect import collect_region_metrics, collect_anomalies
    metrics = collect_region_metrics()
    anoms = collect_anomalies()
    subs = None
    try:
        from engine.realestate_subscriptions import collect_subscriptions
        subs = collect_subscriptions()
    except Exception:
        subs = None
    asof = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")
    st.session_state["re_metrics"] = metrics
    st.session_state["re_anoms"] = anoms
    if subs:
        st.session_state["re_subs"] = subs
    st.session_state["re_asof"] = asof
    # 영속화: 재부팅 후에도·다른 방문자에게도 실데이터가 보이게
    try:
        from modules.db import supabase_configured, save_realestate
        if supabase_configured():
            save_realestate(metrics=metrics, anomalies=anoms,
                            subscriptions=subs, asof=asof)
            _load_re_snapshot.clear()   # 스냅샷 캐시만 무효화
    except Exception:
        pass


def _re_can_collect():
    """갱신(대량 API 호출)은 소유자 전용. APP_PASSWORD 미설정이면 누구나 가능.
       리포트 생성 잠금(gen_authed)을 그대로 재사용해 한 번 풀면 둘 다 열린다."""
    try:
        pw = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        pw = ""
    if not pw or st.session_state.get("gen_authed"):
        return True
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
    return False


def _render_collect_controls():
    """지도 탭 상단 컨트롤 — 데이터 기준 캡션 + 갱신/진단 버튼 + 수집·진단 처리.
       (증시 '새로고침'과 같은 위치: 서브탭 제목 바로 아래.)"""
    asof = st.session_state.get("re_asof")
    if not asof:
        snap = _load_re_snapshot()
        asof = (snap or {}).get("asof") if snap else None
    if asof:
        st.caption(f"수도권 아파트 · 국토부 실거래 기준 {asof} KST · "
                   "가격지표·인구·공급은 샘플(연결 예정)")
    else:
        st.caption("수도권 아파트 · 현재 샘플 데이터 — "
                   "'실거래 갱신'을 누르면 국토부 실거래로 지도·거래가 채워집니다.")

    authed = _re_can_collect()
    col_a, col_b = st.columns([3, 1])
    with col_a:
        do_collect = st.button(
            "🔄 실거래 데이터 갱신", disabled=not authed,
            help="국토부 실거래가 API 수집 (수십 초 소요·API 호출이 많아요)",
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
        with st.spinner("국토부 실거래 수집 중... (지역 지표 + 특이거래)"):
            try:
                _run_collection()
                st.success("실거래 데이터로 갱신했어요.")
                st.rerun()
            except Exception as e:
                st.warning(f"수집 실패 · {e} — 샘플 데이터로 표시합니다.")


def render_realestate():
    """부동산 탭 본문 — 지도 / 지표 / 거래 / 분양 서브탭.

    증시 탭과 동일 구조로 통일: 서브탭을 먼저 두고, 각 서브탭 안에서
    [액센트 바(.accent-bar) + 제목(st.title) + 캡션/컨트롤]로 연다.
    (.accent-bar·h1 스타일은 app.py 전역 CSS를 그대로 사용해 증시와 픽셀 일치.)
    갱신/진단은 주 화면인 '지도' 탭 안에 위치하고, 나머지 탭은 같은 세션/스냅샷을 읽는다.
    """
    st.markdown(_RE_CSS, unsafe_allow_html=True)

    t_map, t_ind, t_anom, t_sub = st.tabs(["지도", "지표", "거래", "분양"])

    with t_map:
        st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
        st.title("수도권 실거래 지도")
        _render_collect_controls()
        _render_map()

    with t_ind:
        st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
        st.title("부동산 시장 지표")
        st.caption("선행·심리 · 가격 · 공급 · 금융 지표를 한눈에 · 직전값 대비 ▲빨강/▼파랑")
        _render_indicators()

    with t_anom:
        st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
        st.title("특이거래")
        st.caption("신고가·신저가·급등락·거래량 급증 · 국토부 실거래 기준 · "
                   "직거래(증여추정) 기본 제외")
        _render_anomalies()

    with t_sub:
        st.markdown('<div class="accent-bar"></div>', unsafe_allow_html=True)
        st.title("분양 단지")
        st.caption("한국부동산원 청약홈 분양정보 · 청약 임박·진행 우선")
        _render_subscriptions()
