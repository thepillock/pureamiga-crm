-- Synthetic Jetpack CRM dump for tests (no real data).
INSERT INTO `wpdv_zbs_contacts` (`ID`, `zbs_site`, `zbsc_status`, `zbsc_email`, `zbsc_fname`, `zbsc_lname`, `zbsc_addr1`, `zbsc_city`, `zbsc_postcode`, `zbsc_mobtel`, `zbsc_created`) VALUES
(1, 1, 'Customer', 'Ada@Example.com', 'Ada', 'O\'Test', '1 Chip Lane', 'Testville', 'te1 1st', '07000 000000', 1645000000),
(2, 1, 'Lead', 'spam@example.com', 'Spammy', '', '', '', '', '', 1645000001),
(3, 1, 'Customer', 'bob@example.com', 'Bob', 'Paula', '', '', '', '', 1645000002);

INSERT INTO `wpdv_zbs_quotes` (`ID`, `zbs_site`, `zbsq_title`, `zbsq_value`, `zbsq_date`, `zbsq_content`, `zbsq_notes`, `zbsq_accepted`, `zbsq_created`, `zbsq_lastupdated`) VALUES
(10, 1, 'A1200 premium recap and \\\"fix video\\\"', '54.00', 1645228800, '<p>Unit arrived.<br />Repair Ref A09</p>\r\n<p>21/2/2022<br />Recapped &amp; tested<br />Video OK</p>\r\n<ul><li>26/2/2022 - Soak tested</li></ul>', '', 1646000000, 1645265848, 1646497714),
(11, 1, 'A1200 again', '20.00', 1700000000, '<p>Repair A09 again</p>', 'Second visit', 0, 1700000000, 1700100000),
(12, 1, 'SX32 repair', '30.00', 1710000000, '', '', 0, 1710000000, 1710100000),
(13, 1, 'Orphan quote', '0.00', 0, '', '', 0, 1710000000, 1710000000);

INSERT INTO `wpdv_zbs_customfields` (`ID`, `zbs_site`, `zbscf_objtype`, `zbscf_objid`, `zbscf_objkey`, `zbscf_objval`, `zbscf_created`) VALUES
(1, 1, 3, 10, 'make-model', 'Amiga A1200', 0),
(2, 1, 3, 10, 'serial-number', 'SN123', 0),
(3, 1, 3, 10, 'parts-sent', '\\\'Board,Lower Shield,Accessories (see list)\\\'', 0),
(4, 1, 3, 10, 'repair-status', 'Returned to customer', 0),
(5, 1, 3, 10, 'bench-time-cost', '35', 0),
(6, 1, 3, 11, 'make-model', 'A1200', 0),
(7, 1, 3, 11, 'serial-number', 'sn123', 0),
(8, 1, 3, 11, 'repair-status', 'Chris - In test', 0),
(9, 1, 3, 12, 'make-model', 'DCE SX32 plus riser', 0),
(10, 1, 3, 12, 'repair-status', 'Chris - Being worked on', 0);

INSERT INTO `wpdv_zbs_object_links` (`ID`, `zbs_site`, `zbsol_objtype_from`, `zbsol_objtype_to`, `zbsol_objid_from`, `zbsol_objid_to`) VALUES
(1, 1, 3, 1, 10, 1),
(2, 1, 3, 1, 11, 1),
(3, 1, 3, 1, 12, 3);
