# Leitor de ARVC

A versão web recebe uma foto do ARVC, usa a API de visão da Groq e permite revisar e exportar os campos. A chave é informada pelo operador no formulário. O aplicativo não grava a chave ou a imagem no servidor.

Na Vercel, importe este repositório com a configuração padrão e use a raiz do projeto. O formulário exige uma imagem JPG, PNG ou WebP de até 3 MiB.

Para preencher o portal no Windows, baixe os arquivos do repositório, instale o Python, execute `py -m pip install playwright` e `py -m playwright install chromium`. Abra `Anexar-ARVC.cmd`, use **Importar revisão** com o JSON baixado e clique em **Preencher no portal**. Faça login, revise o cadastro e salve no portal.
