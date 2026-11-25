# Governação e aprovação independente de outputs

## Estado

Desenho técnico preparado; não existe fluxo de aprovação activo. A libertação de legal hold continua indisponível por omissão. Não foram criadas rotas, permissões, tabelas de pedidos nem eventos de libertação automática nesta fase.

## Invariantes que já são executáveis

- A publicação é imutável e os eventos de governação são append-only.
- Um hold activo bloqueia o consumo do output e, com a linhagem implementada, de todos os derivados conhecidos.
- A libertação só pode ser registada através de um callback de autorização explícito; ausência de callback ou retorno diferente de True é recusa.
- Os trabalhadores não recebem scopes de governação.
- O actor tem de existir e estar activo. Isto é uma condição técnica, não prova independência ou competência legal.

## Fluxo de aprovação proposto

A opção recomendada é um pedido de libertação separado do evento que efectivamente liberta o hold:

1. REQUESTED — um utilizador autenticado apresenta motivo, evidência e publicação/hold alvo. O pedido não altera o estado do hold.
2. APPROVED — um segundo utilizador, diferente do requerente, aprova após revalidar identidade, estado actual, âmbito e evidência.
3. REJECTED ou CANCELLED — o pedido termina sem alterar o hold.
4. Só depois de aprovação válida, o serviço acrescenta LEGAL_HOLD_RELEASED na mesma transacção que marca a aprovação como consumida. O hold permanece activo até esse commit.

A implementação deverá ser append-only, preferencialmente com uma raiz de pedido imutável e eventos sequenciais (REQUESTED, APPROVED, REJECTED, CANCELLED, CONSUMED). A aprovação e o evento LEGAL_HOLD_RELEASED têm de ser atómicos; uma aprovação não consumida não pode desbloquear leituras.

## Separação de funções — proposta, não política activa

- Requerente e aprovador têm de ser utilizadores diferentes.
- Ambos têm de estar activos no momento da operação.
- O aprovador não pode aprovar o próprio pedido, nem reutilizar uma aprovação de outro hold/publicação.
- A autorização tem de ser revalidada sob lock da publicação e do pedido.
- O evento de libertação deve referenciar o ID do pedido aprovado e a evidência correspondente.
- Qualquer conflito, hold substituto, mudança de âmbito, falta de evidência ou falha de auditoria mantém o hold activo.

## Decisões que exigem o responsável do produto/jurídico

1. Quem pode aplicar um legal hold: ADMIN, responsável de privacidade/jurídico, ou uma identidade dedicada?
2. Quem pode pedir a libertação e quem pode aprovar? É obrigatório um segundo administrador ou basta um aprovador de função específica?
3. Há excepções de urgência e quem as pode autorizar?
4. A aprovação é por publicação, por cadeia de derivados, por caso legal ou por conjunto de outputs?
5. Que evidência é obrigatória, onde é armazenada e durante quanto tempo?
6. Qual é a política para utilizadores suspensos, conflitos de interesse e delegações?

Até estas respostas serem aprovadas, todas as operações de libertação devem continuar bloqueadas em qualquer interface exposta. O desenho não assume que ADMIN é automaticamente autoridade jurídica.
