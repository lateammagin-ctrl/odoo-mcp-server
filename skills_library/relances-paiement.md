---
name: relances-paiement
description: Relancer les factures clients en retard de paiement depuis Odoo, facture PDF en annexe, avec l'outil send_payment_reminder.
---

# Relances de paiement

Quand on te demande de relancer les retards de paiement :

1. Liste les factures en retard : `account.move` avec `move_type = out_invoice`,
   `state = posted`, `payment_state` dans `not_paid` / `partial` et
   `invoice_date_due` antérieure à aujourd'hui. Regroupe-les par client
   (`commercial_partner_id`).
2. Rappelle qu'un paiement peut être arrivé sans être encore lettré
   (synchronisation bancaire, SumUp, Stripe) : signale-le avant d'envoyer.
3. Choisis le niveau de relance par client, sauf consigne contraire :
   - « Payment Reminder » (id 44) : premier rappel.
   - « Rappel de paiement (2) » (id 51) : un rappel a déjà été envoyé.
   - « Rappel de paiement (3) » (id 52) : mise en demeure, mentionne la voie
     judiciaire. Ne l'utilise jamais sans accord explicite.
   Pour savoir si un rappel est déjà parti, regarde `audit_log` (opération
   `send_payment_reminder`) et les notes « Relance de paiement » des factures.
4. Appelle `send_payment_reminder(partner_id, template_id)` une fois par
   client. Sans `invoice_ids`, toutes ses factures échues sont jointes.
   Utilise `recipient_partner_ids` quand le client a un contact comptabilité
   (contact enfant de type facturation) : c'est lui qui doit recevoir le mail.
5. Le premier appel renvoie un aperçu (destinataires, factures, total) :
   montre la liste complète à l'utilisateur et attends son feu vert, puis
   rappelle l'outil avec `confirmation_token`.
6. Après l'envoi, résume : clients relancés, niveau, montants.
