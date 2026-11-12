# Provider OCR PaddleOCR

## Decisão técnica

O primeiro adaptador experimental usa PaddleOCR 3.x com PP-OCRv5 e idioma
português. O motor é opcional e não é importado pela API nem pelo worker de
visão quando o provider não é explicitamente instanciado.

A dependência está isolada em `apps/api/requirements-ocr.txt`. Instalar
primeiro o runtime PaddlePaddle CPU compatível com a plataforma, seguindo a
documentação oficial; depois instalar este ficheiro. Não adicionar estas
dependências à instalação base da API.

## Contrato

`app.ocr_paddle.PaddleOCRProvider.recognize(path)` devolve uma sequência de
`OCRRegion`, cada uma com `OCRText(text, confidence)` e caixa normalizada
`x_min/y_min/x_max/y_max` entre 0 e 1. A implementação usa o método
`predict(input=...)` do PaddleOCR 3.x e aceita resultados em mapping ou
objetos com propriedade/método `.json`.

## Instalação CPU (exemplo Linux)

```bash
cd apps/api
python -m pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
python -m pip install -r requirements-ocr.txt
```

A instalação de PaddlePaddle pode variar por sistema operativo, arquitetura e
versão de Python. Confirmar a matriz oficial antes de instalar noutros
ambientes.

## Limitações e segurança

- O adaptador não faz matching de SKU, não aprova produtos e não altera stock.
- Scores OCR são confiança do reconhecimento, não probabilidade de SKU correto.
- Caixas OCR são regiões de texto, não caixas de produtos.
- Não está ligado ao worker de visão nem executou inferência real nesta fase.
- O teste usa um motor simulado; valida transformação de resultados e erros,
  não mede precisão OCR.
- Verificar licença do código e dos pesos concretos antes de distribuição.
  O repositório PaddleOCR declara Apache-2.0; manter os avisos aplicáveis.

## Próximo passo

Ligar este provider por configuração opcional ao worker, preservar as regiões
OCR por deteção de produto e executar um benchmark com fotografias reais
autorizadas, incluindo texto pequeno, reflexos, curvatura e variantes.


A associação por produto está documentada em [OCR e associação a deteções](ocr-detection-association.md). O adaptador usa `rec_polys`, alinhado com `rec_texts` e `rec_scores`; não deve usar `dt_polys` para esse alinhamento, pois pode conter caixas não reconhecidas.
