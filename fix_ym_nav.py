import re

YM_BLOCK = """<script type="text/javascript">
(function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};
m[i].l=1*new Date();
for(var j=0;j<document.scripts.length;j++){if(document.scripts[j].src===r){return;}}
k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)
})(window,document,"script","https://mc.yandex.ru/metrika/tag.js","ym");
ym(108361513,"init",{clickmap:true,trackLinks:true,accurateTrackBounce:true});
</script>
<noscript><div><img src="https://mc.yandex.ru/watch/108361513" style="position:absolute;left:-9999px;" alt=""/></div></noscript>"""

NAV_BUTTON = '<a href="support.html" style="background:#e74c3c;color:#fff;padding:4px 10px;border-radius:4px;text-decoration:none;font-weight:bold;">❤️ Поддержать</a>'

with open("docs/index.html", "r", encoding="utf-8") as f:
    html = f.read()

if "108361513" not in html:
    html = html.replace("</head>", YM_BLOCK + "\n</head>", 1)
    print("YM: вставлена")
else:
    print("YM: уже есть, пропускаем")

if "support.html" not in html:
    html = re.sub(r'(flood-guide\.html[^<]*</a>)', r'\1 ' + NAV_BUTTON, html, count=1)
    print("Кнопка ❤️: вставлена")
else:
    print("Кнопка ❤️: уже есть, пропускаем")

with open("docs/index.html", "w", encoding="utf-8") as f:
    f.write(html)

print("ГОТОВО")
